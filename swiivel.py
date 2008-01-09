#! /usr/bin/env python

import math
import os.path;
import random;
import sys
import thread
import time

from wmd.Common import *
from wmd.Config import CFG
from wmd.EVDispatcher import EVDispatcher
from wmd.UI.UIManager import UIManager
from wmd.CommandMapper import CommandMapper
from wmd.Pointer import POManager
from wmd.Wiimote.WMManager import WMManager

from wmd.Wiimote.Input import ReportParser, WiimoteState


#import basic pygame modules
import pygame
from pygame.locals import *

#see if we can load more than standard BMP
if not pygame.image.get_extended():
    raise SystemExit, "Sorry, extended image module required"


#game constants
MAX_SHOTS      = 5      #most player bullets onscreen
ALIEN_ODDS     = 120     #chances a new alien appears
BOMB_ODDS      = 60    #chances a new bomb will drop
ALIEN_RELOAD   = 12     #frames between new aliens
WIDTH          = 800;
HEIGHT         = 400;
SCREENRECT     = Rect(0, 0, WIDTH, HEIGHT)
SCORE          = 0

event_dispatcher = None;

players = {};
connected_wiimotes = {};

def load_image(file):
    "loads an image, prepares it for play"
    file = os.path.join('data', file)
    try:
        surface = pygame.image.load(file)
    except pygame.error:
        raise SystemExit, 'Could not load image "%s" %s'%(file, pygame.get_error())
    return surface.convert()

def load_images(*files):
    imgs = []
    for file in files:
        imgs.append(load_image(file))
    return imgs


class dummysound:
    def play(self): pass

def load_sound(file):
    if not pygame.mixer: return dummysound()
    file = os.path.join('data', file)
    try:
        sound = pygame.mixer.Sound(file)
        return sound
    except pygame.error:
        print 'Warning, unable to load,', file
    return dummysound()



# each type of game object gets an init and an
# update function. the update function is called
# once per frame, and it is when each object should
# change it's current position and state. the Player
# object actually gets a "move" function instead of
# update, since it is passed extra information about
# the keyboard


class Player(pygame.sprite.Sprite):
    speed = 5
    bounce = 24
    gun_offset = -11
    images = []
    shoot_sound = load_sound('car_door.wav')
    
    def __init__(self):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image = self.images[0]
        self.rect = self.image.get_rect(midbottom=SCREENRECT.midbottom)
        self.reloading = 0
        self.origtop = self.rect.top
        self.facing = -1
        self.cursor = [0,0]
        self.shots = pygame.sprite.Group()
        self.hDirection = self.vDirection = self.firing = 0;

    def update(self):
        if self.hDirection: self.facing = self.hDirection
        self.rect.move_ip(self.hDirection*self.speed, self.vDirection*self.speed)
        self.rect = self.rect.clamp(SCREENRECT)
        if self.hDirection < 0:
            self.image = self.images[0]
        elif self.hDirection > 0:
            self.image = self.images[1]
        #self.rect.top = self.origtop - (self.rect.left/self.bounce%2)

        if self.firing and not self.reloading and len(self.shots) < MAX_SHOTS:
            self.shots.add(Shot(self.gunpos(), self.turret_vector()));
            self.shoot_sound.play()
        self.reloading = self.firing

    def gunpos(self):
        pos = self.facing*self.gun_offset + self.rect.centerx
        return pos, self.rect.top

    def drawcursor(self, surface):
        return pygame.draw.aaline(surface, [255,0,0], self.gunpos(), self.cursor)

    def turret_vector(self):
	dx = self.cursor[0] - self.gunpos()[0];
	dy = self.cursor[1] - self.gunpos()[1];
	mag = math.sqrt(dx*dx + dy*dy)
	if (mag == 0) : return [0, 0]
        return [dx / mag, dy / mag]


class Alien(pygame.sprite.Sprite):
    speed = 5
    animcycle = 12
    images = []
    def __init__(self):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image = self.images[0]
        self.rect = self.image.get_rect()
        self.facing = random.choice((-1,1)) * Alien.speed
        self.frame = 0
        if self.facing < 0:
            self.rect.right = SCREENRECT.right

    def update(self):
        self.rect.move_ip(self.facing, 0)
        if not SCREENRECT.contains(self.rect):
            self.facing = -self.facing;
            self.rect.top = self.rect.bottom + 1
            self.rect = self.rect.clamp(SCREENRECT)
        self.frame = self.frame + 1
        self.image = self.images[self.frame/self.animcycle%3]
        if not int(random.random() * BOMB_ODDS):
            Bomb(self)

    def drawcursor(self, surface):
        pass

class Explosion(pygame.sprite.Sprite):
    defaultlife = 12
    animcycle = 3
    images = []
    def __init__(self, actor):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image = self.images[0]
        self.rect = self.image.get_rect(center=actor.rect.center)
        self.life = self.defaultlife

    def update(self):
        self.life = self.life - 1
        self.image = self.images[self.life/self.animcycle%2]
        if self.life <= 0: self.kill()


class Shot(pygame.sprite.Sprite):
    speed = 11
    images = []
    def __init__(self, pos, direction):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image = self.images[0]
        self.rect = self.image.get_rect(midbottom=pos)
 	self.direction = direction

    def update(self):
        self.rect.move_ip(self.speed * self.direction[0], self.speed * self.direction[1])
        if (not SCREENRECT.contains(self.rect)):
            self.kill()


class Bomb(pygame.sprite.Sprite):
    speed = 9
    images = []
    def __init__(self, alien):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image = self.images[0]
        self.rect = self.image.get_rect(midbottom=
                    alien.rect.move(0,50).midbottom)

    def update(self):
        self.rect.move_ip(0, self.speed)
        if self.rect.bottom >= 470:
            Explosion(self)
            self.kill()


class Score(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.font = pygame.font.Font(None, 20)
        self.font.set_italic(1)
        self.color = Color('white')
        self.lastscore = -1
        self.update()
        self.rect = self.image.get_rect().move(10, 450)

    def update(self):
        if SCORE != self.lastscore:
            self.lastscore = SCORE
            msg = "Score: %d" % SCORE
            self.image = self.font.render(msg, 0, self.color)

def main(winstyle = 0):
    # Initialize pygame
    pygame.init()
    if pygame.mixer and not pygame.mixer.get_init():
        print 'Warning, no sound'
        pygame.mixer = None

    # Set the display mode
    winstyle = 0 # |FULLSCREEN
    bestdepth = pygame.display.mode_ok(SCREENRECT.size, winstyle, 32)
    screen = pygame.display.set_mode(SCREENRECT.size, winstyle, bestdepth)

    #Load images, assign to sprite classes
    #(do this before the classes are used, after screen setup)
    img = load_image('player1.gif')
    Player.images = [img, pygame.transform.flip(img, 1, 0)]
    img = load_image('explosion1.gif')
    Explosion.images = [img, pygame.transform.flip(img, 1, 1)]
    Alien.images = load_images('alien1.gif', 'alien2.gif', 'alien3.gif')
    Bomb.images = [load_image('bomb.gif')]
    Shot.images = [load_image('shot.gif')]

    #decorate the game window
    icon = pygame.transform.scale(Alien.images[0], (32, 32))
    pygame.display.set_icon(icon)
    pygame.display.set_caption('Pygame Aliens')
    #pygame.mouse.set_visible(0)

    #create the background, tile the bgd image
    bgdtile = load_image('background.gif')
    background = pygame.Surface(SCREENRECT.size)
    for x in range(0, SCREENRECT.width, bgdtile.get_width()):
        background.blit(bgdtile, (x, 0))
    screen.blit(background, (0,0))
    pygame.display.flip()

    #load the sound effects
    boom_sound = load_sound('boom.wav')
    if pygame.mixer:
        music = os.path.join('data', 'house_lo.wav')
        pygame.mixer.music.load(music)
        pygame.mixer.music.play(-1)

    # Initialize Game Groups
    tanks = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    all = pygame.sprite.RenderUpdates()

    #assign default groups to each sprite class
    Player.containers = tanks, all
    Alien.containers = tanks, all
    Shot.containers = shots, all
    Bomb.containers = shots, all
    Explosion.containers = all
    #Score.containers = all

    #Create Some Starting Values
    global score
    kills = 0
    # clock = pygame.time.Clock()
    # NB: it seems that clock.tick does not let other threads run?

    #initialize our starting sprites
    global SCORE


    #if pygame.font:
        #all.add(Score())

    # local (non-wiimote) player thread
    p = Player();
    players[0] = p;
    thread.start_new_thread(player_loop, (p,));

    while True:

        #Check for game end
        for event in pygame.event.get():
            if (event.type == QUIT or 
                (event.type == KEYDOWN and event.key == K_ESCAPE)):
                    print "Shutting down...";
                    event_dispatcher.send( EV_SHUTDOWN, '' )
                    time.sleep(1);
                    return 

        # clear/erase the last drawn sprites
        #all.clear(screen, background)
	screen.blit(background, (0,0))

        #update all the sprites
        all.update()


        # Create new alien
        if not int(random.random() * ALIEN_ODDS):
            Alien()

        for tank in pygame.sprite.groupcollide(shots, tanks, 1, 1).keys():
            boom_sound.play()
            Explosion(tank)
            tank.kill()

        #draw the scene
        dirty = all.draw(screen);
        for tank in tanks:
            dirty.append(tank.drawcursor(screen));
        pygame.display.update(SCREENRECT)
	
        #cap the framerate
        #clock.tick(40)
        time.sleep(0.025);

    if pygame.mixer:
        pygame.mixer.music.fadeout(1000)
    pygame.time.wait(1000)

def wiimote_loop(ev, cf):
    ev.subscribe(ABS_POS, ev_abs_pos);
    ev.subscribe(WM_BT, ev_wm_bt);

    while(True):
	btaddr = sys.stdin.readline().rstrip();
	if (not btaddr):
            for addr in cf['KNOWN_WIIMOTES']:
                if ((not addr in connected_wiimotes) or
                    (not connected_wiimotes[addr].running)):
                     btaddr = addr;
                     break;
             
        if (btaddr):
          print "Connecting to " + btaddr;
          cf['MY_WIIMOTE_ADDR'] = btaddr
          wm = WMManager( cf, ev ) # Handles the Wiimote; connects to it, manages wiimote state and mode, parses wiimote reports
          po = POManager( cf, ev, wm.id ) # Handles the pointer, receives WM_IR, sends out ABS_POS absolute position reports

          try:
              if wm.connect() and wm.setup():
                  thread.start_new_thread(wm.main_loop, ())
                  players[wm.id] = Player();
                  connected_wiimotes[btaddr] = wm; 
          except Exception, reason:
              # continue the thread
              print "Exception: " + str(reason);

# Keyboard/mouse monitor for a local (non-wiimote) player
def player_loop(player):
    while True:
        player.cursor = pygame.mouse.get_pos();
        keystate = pygame.key.get_pressed();
        player.hDirection = keystate[K_RIGHT] - keystate[K_LEFT]
        player.vDirection = keystate[K_DOWN] - keystate[K_UP]
        player.firing = keystate[K_SPACE]
        if (player.firing and
            not player.groups()):
            # respawn
            players[0] = player = Player();

        #cap the framerate
        #pygame.time.Clock().tick(40);
        time.sleep(0.025);


# handler for absolute cursor events
def ev_abs_pos(pos, id):
    if not (id in players):
        return;
    p = players[id];
    if (p):
        p.cursor[0] = pos[0] * WIDTH;
        p.cursor[1] = pos[1] * HEIGHT;

# handler for button events
def ev_wm_bt(event, id):
    if not (id in players):
        return;
    p = players[id];
    if (p):
        down = (event[1] == 'DOWN');
        #stupid python, having no ternary expression
        magnitude = 0;
        if (down):
            magnitude = 1;
        if (event[0] == 'D'):
            p.vDirection = magnitude;
        elif (event[0] == 'U'):
            p.vDirection = -1 * magnitude;
        elif (event[0] == 'L'):
            p.hDirection = -1 * magnitude;
        elif (event[0] == 'R'):
            p.hDirection = 1 * magnitude
        elif (event[0] == 'A'):
            p.firing = down;
        elif (event[0] == 'B'):
            pass #todo: mines
    if (not p.groups() and event[0] == 'A' and event[1] == 'UP'):
        # respawn
        players[id] = Player();        

#call the "main" function if running this script
if __name__ == '__main__':
    # kick off the thread to search for wiimotes
    cf = CFG
    event_dispatcher = EVDispatcher( cf );
    thread.start_new_thread(wiimote_loop, (event_dispatcher, cf));
    # main game loop
    main()
