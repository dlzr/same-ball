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

    STATE_GONE = -1
    STATE_IDLE = 0
    STATE_SPINNING = 1
    STATE_DROP = 2
    STATE_VANISH = 3

    SPIN_DURATION_S = 2.0

    Z_VIEWER = 5  # Cells.
    VANISH_ACCEL = 500  # Cells / s^2.
    VANISH_DURATION_S = 0.250

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

    def __init__(self, board, col, row, group):
        super(Ball, self).__init__(group)
        self.board = board
        self.col = col
        self.row = row
        self.color = random.choice(Ball.COLORS)
        self.rotation = random.random()
        self.spin_t = board.t
        self.image = self.get_image()
        self.rect = self.board.rect(col, row, 1, 1)
        self.cluster = pygame.sprite.RenderUpdates(self)
        self.state = Ball.STATE_IDLE

    def get_rotation(self):
        return (self.rotation +
                ((self.board.t - self.spin_t) % Ball.SPIN_DURATION_S) /
                Ball.SPIN_DURATION_S) % 1.0

    def get_image(self):
        return self.color[int(self.get_rotation() * len(self.color))]

    def get_vanish_size(self):
        return (Ball.Z_VIEWER /
                (Ball.Z_VIEWER +
                 Ball.VANISH_ACCEL * ((self.board.t - self.vanish_t)**2)))

    def start_spinning(self):
        self.state = Ball.STATE_SPINNING
        self.spin_t = self.board.t

    def stop_spinning(self):
        self.state = Ball.STATE_IDLE
        self.rotation = self.get_rotation()

    def vanish(self):
        self.state = Ball.STATE_VANISH
        self.vanish_t = self.board.t

    def update(self):
        if self.state == Ball.STATE_GONE:
            return

        elif self.state == Ball.STATE_SPINNING:
            self.image = self.get_image()

        elif self.state == Ball.STATE_VANISH:
            if (self.board.t - self.vanish_t) >= Ball.VANISH_DURATION_S:
                self.board.remove_ball(self)
                self.state = Ball.STATE_GONE
                return

            image = self.get_image()
            size = self.get_vanish_size()
            self.image = pygame.transform.scale(
                    image, (int(size * Ball.SIZE), int(size * Ball.SIZE)))
            self.rect = self.board.rect(self.col + 0.5 - size / 2,
                                        self.row + 0.5 - size / 2,
                                        size, size)


class Board(object):

    def __init__(self, surface, num_columns, num_rows, game_seed=''):
        self.surface = surface
        self.num_columns = num_columns
        self.num_rows = num_rows

        self.game_seed = game_seed or generate_game_seed()
        random.seed(base64.b32decode(self.game_seed, casefold=True))

        ball_size = min(self.surface.get_width() // num_columns,
                        self.surface.get_height() // num_rows)
        self.padding_x = (self.surface.get_width() - ball_size*num_columns) // 2
        self.padding_y = (self.surface.get_height() - ball_size*num_rows) // 2
        Ball.init(ball_size)

        self.t = time.time()
        self.all_balls = pygame.sprite.RenderUpdates()
        self.balls = [[Ball(self, col, row, self.all_balls)
                       for row in range(num_rows)]
                      for col in range(num_columns)]
        self.cluster_balls()

        self.spinning_cluster = None
        self.vanishing_cluster = None

    def rect(self, col, row, width, height):
        """col, row, width and height are all in cells."""
        return pygame.Rect(int(self.padding_x + col * Ball.SIZE),
                           int(self.padding_y + row * Ball.SIZE),
                           int(width * Ball.SIZE),
                           int(height * Ball.SIZE))

    def update(self):
        self.t = time.time()
        self.all_balls.update()

    def draw(self):
        self.surface.fill((32, 32, 38))
        return self.all_balls.draw(self.surface)

    def cluster_balls(self):
        def cluster(ball1, ball2):
            if ball1 is None or ball2 is None:
                return
            if ball1.color == ball2.color and ball1.cluster != ball2.cluster:
                ball1.cluster.add(*ball2.cluster.sprites())
                old_cluster = ball2.cluster
                for ball in old_cluster.sprites():
                    ball.cluster = ball1.cluster
                old_cluster.empty()

        for col in range(self.num_columns - 1):
            for row in range(self.num_rows):
                cluster(self.balls[col][row], self.balls[col+1][row])

        for col in range(self.num_columns):
            for row in range(self.num_rows - 1):
                cluster(self.balls[col][row], self.balls[col][row+1])

    def ball_at(self, x, y):
        col = int((x - self.padding_x) / Ball.SIZE)
        row = int((y - self.padding_y) / Ball.SIZE)
        if col < 0 or col >= self.num_columns or row < 0 or row >= self.num_rows:
            return None
        return self.balls[col][row]

    def start_spinning_cluster(self, cluster):
        self.spinning_cluster = cluster
        for ball in cluster.sprites():
            ball.start_spinning()

    def stop_spinning_cluster(self):
        if not self.spinning_cluster:
            return

        for ball in self.spinning_cluster:
            ball.stop_spinning()
        self.spinning_cluster = None

    def kill_spinning_cluster(self):
        if not self.spinning_cluster:
            raise RuntimeError("Board.kill_spinning_cluster() called unexpectedly.")

        self.vanishing_cluster = self.spinning_cluster
        self.spinning_cluster = None

        for ball in self.vanishing_cluster:
            self.balls[ball.col][ball.row] = None
            ball.vanish()

    def remove_ball(self, ball):
        if ball.state != Ball.STATE_VANISH:
            raise RuntimeError("Board.remove_ball() called unexpectedly.")

        self.all_balls.remove(ball)
        self.vanishing_cluster.remove(ball)
        if not self.vanishing_cluster:
            self.vanishing_cluster = None



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
        self.board.update()
        pygame.display.update(self.board.draw())
        return True

    def on_mouse_move(self, widget, event=None):
        ball = self.board.ball_at(event.x, event.y)
        if not ball:
            self.board.stop_spinning_cluster()
            return
        if ball.state == Ball.STATE_SPINNING:
            return
        self.board.stop_spinning_cluster()
        if len(ball.cluster) > 1:
            self.board.start_spinning_cluster(ball.cluster)

    def on_mouse_click(self, widget, event=None):
        ball = self.board.ball_at(event.x, event.y)
        if not ball:
            return
        if ball.state == Ball.STATE_SPINNING:
            self.board.kill_spinning_cluster()

    def on_resize(self, widget, event=None):
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()), 0, 0)
        self.update()

    def on_quit(self, widget, data=None):
        Gtk.main_quit()


if __name__ == '__main__':
    app = SameBallApp()
    app.run()
