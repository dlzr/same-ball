#!/usr/bin/python

from __future__ import division

from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import GdkX11
from gi.repository import Gtk
import base64
import hashlib
import math
import os
import pygame
import random
import re
import time


FPS = 30
FRAME_DURATION_MS = int(1000 / FPS)


def generate_game_seed():
    return base64.b32encode(hashlib.sha256(str(time.time())).digest()[:5])


class Ball(pygame.sprite.Sprite):

    IMAGES = []
    COLORS = []
    SIZE = 64

    @staticmethod
    def load_images():
        Ball.IMAGES = [pygame.image.load(f)
                       for f in ['blue.png', 'green.png', 'purple.png',
                                 'red.png', 'white.png', 'yellow.png']]

    @staticmethod
    def init(ball_size):
        Ball.SIZE = ball_size
        Ball.COLORS = [Ball.split_frames(film) for film in Ball.IMAGES]

    @staticmethod
    def split_frames(film):
        if film.get_height() > film.get_width():
            raise ValueError('Ball sprites should have a sequence of frames '
                             'laid out horizontally next to each other')

        frames = []
        size = film.get_height()
        num_frames = film.get_width() // size
        for i in range(num_frames):
            frame = pygame.Surface((size, size), 0, film)
            frame.blit(film, (0, 0), pygame.Rect(i*size, 0, size, size))
            frames.append(pygame.transform.smoothscale(frame,
                                                       (Ball.SIZE, Ball.SIZE)))
        return frames

    def __init__(self, col, row, group):
        super(Ball, self).__init__(group)
        self.color = random.choice(Ball.COLORS)
        self.frame_idx = random.randrange(len(self.color))
        self.image = self.color[self.frame_idx]
        self.rect = pygame.Rect(col * Ball.SIZE, row * Ball.SIZE,
                                Ball.SIZE, Ball.SIZE)


class Board(object):
    
    def __init__(self, surface, num_columns, num_rows, game_seed=''):
        self.surface = surface

        self.game_seed = game_seed or generate_game_seed()
        random.seed(base64.b32decode(self.game_seed, casefold=True))

        Ball.init(min(self.surface.get_width() // num_columns,
                      self.surface.get_height() // num_rows))

        self.all_balls = pygame.sprite.RenderUpdates()
        self.balls = [[Ball(c, r, self.all_balls) for r in range(num_rows)]
                       for c in range(num_columns)]

    def draw(self):
        return self.all_balls.draw(self.surface)


class SameBallApp(object):

    def __init__(self):
        self.init_ui()
        self.load_images()
        self.board = Board(self.screen, 10, 7)

    def init_ui(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file('same-ball.glade')
        self.builder.connect_signals(self)

        self.window = self.builder.get_object('main_window')
        self.window.show_all()
        self.window.connect('delete-event', self.on_quit)

        self.game_area = self.builder.get_object('game_area')
        self.game_area.realize()
        os.putenv('SDL_WINDOWID', str(self.game_area.get_window().get_xid()))
        Gdk.flush()

        pygame.init()
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()), 
                                 pygame.DOUBLEBUF, 0)
        self.screen = pygame.display.get_surface()

        self.game_area.connect('configure-event', self.on_resize)
        window = self.game_area.get_window()
        window.set_events(window.get_events() |
                          Gdk.EventMask.POINTER_MOTION_MASK |
                          Gdk.EventMask.BUTTON_PRESS_MASK)
        self.game_area.connect('motion-notify-event', self.on_mouse_move)
        self.game_area.connect('button-press-event', self.on_mouse_click)

    def load_images(self):
        Ball.load_images()

    def run(self):
        GObject.timeout_add(FRAME_DURATION_MS, self.update)
        Gtk.main()

    def update(self):
        pygame.display.update(self.board.draw())
        return True

    def on_mouse_move(self, widget, event=None):
#        print "Mouse at: ({}, {})".format(event.x, event.y)
        pass

    def on_mouse_click(self, widget, event=None):
        print "Mouse clicked at: ({}, {})".format(event.x, event.y)

    def on_resize(self, widget, event=None):
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()), 0, 0)
        self.update()

    def on_quit(self, widget, data=None):
        Gtk.main_quit()


if __name__ == '__main__':
    app = SameBallApp()
    app.run()
