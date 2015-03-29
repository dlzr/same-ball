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


BG_COLOR = Gdk.color_parse('#202026')


def generate_game_seed():
    return base64.b32encode(hashlib.sha256(str(time.time())).digest()[:5])

def to_pygame(gdk_color):
    return (gdk_color.red / 256,
            gdk_color.green / 256,
            gdk_color.blue / 256)

class Ball(pygame.sprite.Sprite):

    IMAGES = []
    COLORS = []
    SIZE = 64

    STATE_GONE = -1
    STATE_IDLE = 0
    STATE_SPIN = 1
    STATE_DROP = 2
    STATE_VANISH = 3

    SPIN_DURATION_S = 2.0

    VANISH_DURATION_S = 0.250
    VANISH_ACCEL = 500  # Cells / s^2.
    Z_VIEWER = 5  # Cells.

    DROP_ACCEL_COL = 10
    DROP_ACCEL_ROW = 10

    @staticmethod
    def load_images():
        Ball.IMAGES = [pygame.image.load(f)
                       for f in ['blue.png', 'green.png', 'purple.png',
                                 'red.png', 'white.png', 'yellow.png']]

    @staticmethod
    def init(num_colors):
        random.shuffle(Ball.IMAGES)
        Ball.NUM_COLORS = min(num_colors, len(Ball.IMAGES))

    @staticmethod
    def resize_images(ball_size):
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
        self.drop_col = col
        self.drop_row = row
        self.color = random.randrange(Ball.NUM_COLORS)
        self.rotation = random.random()
        self.spin_t = board.t
        self.state = Ball.STATE_IDLE
        self.cluster = None

        self.resize()

    def resize(self):
        self.image = self.get_image()
        self.rect = self.board.rect(self.col, self.row, 1, 1)

    def get_image(self):
        images = Ball.COLORS[self.color]
        return images[int(self.get_rotation() * len(images))]

    def start_spinning(self):
        self.state = Ball.STATE_SPIN
        self.spin_t = self.board.t

    def stop_spinning(self):
        self.rotation = self.get_rotation()
        self.state = Ball.STATE_IDLE

    def get_rotation(self):
        if self.state == Ball.STATE_SPIN:
            return (self.rotation +
                    ((self.board.t - self.spin_t) % Ball.SPIN_DURATION_S) /
                    Ball.SPIN_DURATION_S) % 1.0
        return self.rotation

    def vanish(self):
        self.state = Ball.STATE_VANISH
        self.vanish_t = self.board.t

    def get_vanish_size(self):
        return (Ball.Z_VIEWER /
                (Ball.Z_VIEWER +
                 Ball.VANISH_ACCEL * (self.board.t - self.vanish_t)**2))

    def drop_vertically(self, num_rows):
        self.state = Ball.STATE_DROP
        self.drop_t = self.board.t
        self.drop_row += num_rows

    def drop_horizontally(self, num_cols):
        self.state = Ball.STATE_DROP
        self.drop_t = self.board.t
        self.drop_col -= num_cols

    def stop_dropping(self):
        self.state = Ball.STATE_IDLE
        self.col = self.drop_col
        self.row = self.drop_row
        self.board.stop_dropping_ball(self)

    def get_drop_position(self):
        col = self.col - Ball.DROP_ACCEL_COL * (self.board.t - self.drop_t)**2
        col = max(col, self.drop_col)
        row = self.row + Ball.DROP_ACCEL_ROW * (self.board.t - self.drop_t)**2
        row = min(row, self.drop_row)
        return (col, row)

    def update(self):
        if self.state == Ball.STATE_GONE:
            return

        elif self.state == Ball.STATE_SPIN:
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

        elif self.state == Ball.STATE_DROP:
            col, row = self.get_drop_position()
            self.rect = self.board.rect(col, row, 1, 1)
            if (col, row) == (self.drop_col, self.drop_row):
                self.stop_dropping()


class Board(object):

    def __init__(self, surface, num_colors, num_columns, num_rows, game_seed=''):
        self.surface = surface
        self.num_columns = num_columns
        self.num_rows = num_rows

        self.game_seed = game_seed or generate_game_seed()
        random.seed(base64.b32decode(self.game_seed, casefold=True))

        Ball.init(num_colors)
        self.all_balls = pygame.sprite.RenderUpdates()
        self.resize()

        self.t = time.time()
        self.balls = [[Ball(self, col, row, self.all_balls)
                       for row in range(num_rows)]
                      for col in range(num_columns)]
        self.cluster_balls()

        self.spinning_cluster = None
        self.vanishing_cluster = None
        self.dropping_cluster = None
        self.dropped_cluster = pygame.sprite.RenderUpdates()

        self.block_events = False

        self.score = 0

    def ball_at(self, x, y):
        col = int((x - self.padding_x) / Ball.SIZE)
        row = int((y - self.padding_y) / Ball.SIZE)
        if col < 0 or col >= self.num_columns or row < 0 or row >= self.num_rows:
            return None
        return self.balls[col][row]

    def rect(self, col, row, width, height):
        """col, row, width and height are all in cells."""
        return pygame.Rect(int(self.padding_x + col * Ball.SIZE),
                           int(self.padding_y + row * Ball.SIZE),
                           int(width * Ball.SIZE),
                           int(height * Ball.SIZE))

    def resize(self):
        ball_size = min(self.surface.get_width() // self.num_columns,
                        self.surface.get_height() // self.num_rows)
        self.padding_x = (self.surface.get_width() - ball_size*self.num_columns) // 2
        self.padding_y = (self.surface.get_height() - ball_size*self.num_rows) // 2
        Ball.resize_images(ball_size)

        for ball in self.all_balls.sprites():
            ball.resize()

    def show(self):
        self.surface.fill(to_pygame(BG_COLOR))
        self.all_balls.draw(self.surface)

    def update(self):
        self.t = time.time()

        update_rects = []
        update_rects.extend(self.undraw())

        if self.spinning_cluster:
            self.spinning_cluster.update()
        if self.vanishing_cluster:
            self.vanishing_cluster.update()
        if self.dropping_cluster:
            self.dropping_cluster.update()

        update_rects.extend(self.draw())
        return update_rects

    def has_updates(self):
        return self.spinning_cluster or self.vanishing_cluster or self.dropping_cluster

    def draw(self):
        update_rects = []
        if self.spinning_cluster:
            update_rects.extend(self.spinning_cluster.draw(self.surface))
        if self.vanishing_cluster:
            update_rects.extend(self.vanishing_cluster.draw(self.surface))
        if self.dropping_cluster:
            update_rects.extend(self.dropping_cluster.draw(self.surface))
        if self.dropped_cluster:
            update_rects.extend(self.dropped_cluster.draw(self.surface))
            self.dropped_cluster.empty()
        return update_rects

    def undraw(self):
        update_rects = []

        def undraw_cluster(cluster):
            if not cluster:
                return
            for ball in cluster.sprites():
                self.surface.fill(to_pygame(BG_COLOR), ball.rect)
                update_rects.append(ball.rect)

        undraw_cluster(self.spinning_cluster)
        undraw_cluster(self.vanishing_cluster)
        undraw_cluster(self.dropping_cluster)

        return update_rects

    def cluster_balls(self):
        self.has_clusters = False

        def cluster(ball1, ball2):
            if ball1 is None or ball2 is None:
                return
            if ball1.color == ball2.color and ball1.cluster != ball2.cluster:
                ball1.cluster.add(*ball2.cluster.sprites())
                old_cluster = ball2.cluster
                for ball in old_cluster.sprites():
                    ball.cluster = ball1.cluster
                old_cluster.empty()
                self.has_clusters = True

        for col_balls in self.balls:
            for ball in col_balls:
                if ball:
                    if ball.cluster:
                        ball.cluster.remove(ball)
                    ball.cluster = pygame.sprite.RenderUpdates(ball)

        for col in range(self.num_columns - 1):
            for row in range(self.num_rows):
                cluster(self.balls[col][row], self.balls[col+1][row])

        for col in range(self.num_columns):
            for row in range(self.num_rows - 1):
                cluster(self.balls[col][row], self.balls[col][row+1])

    def start_spinning_cluster(self, cluster):
        self.t = time.time()
        self.spinning_cluster = cluster
        for ball in cluster.sprites():
            ball.start_spinning()

    def stop_spinning_cluster(self):
        self.t = time.time()
        if not self.spinning_cluster:
            return

        for ball in self.spinning_cluster:
            ball.stop_spinning()
        self.spinning_cluster = None

    def kill_spinning_cluster(self):
        self.t = time.time()
        if not self.spinning_cluster:
            raise RuntimeError("Board.kill_spinning_cluster() called unexpectedly.")

        self.block_events = True

        self.vanishing_cluster = self.spinning_cluster
        self.spinning_cluster = None

        for ball in self.vanishing_cluster:
            self.balls[ball.col][ball.row] = None
            ball.vanish()

        n = len(self.vanishing_cluster)
        self.score += n * (n - 1)

    def remove_ball(self, ball):
        if ball.state != Ball.STATE_VANISH:
            raise RuntimeError("Board.remove_ball() called unexpectedly.")

        self.all_balls.remove(ball)
        self.vanishing_cluster.remove(ball)
        if not self.vanishing_cluster:
            self.vanishing_cluster = None
            self.drop_balls()

    def drop_balls(self):
        def drop_horizontally(col, num_empty_cols):
            for ball in self.balls[col]:
                if ball:
                    ball.drop_horizontally(num_empty_cols)
                    self.dropping_cluster.add(ball)

        def drop_vertically(col):
            num_empty_rows = 0
            for row in range(self.num_rows - 1, -1, -1):
                ball = self.balls[col][row]
                if ball is None:
                    num_empty_rows += 1
                elif num_empty_rows:
                    ball.drop_vertically(num_empty_rows)
                    self.dropping_cluster.add(ball)
            return int(num_empty_rows == self.num_rows)

        self.dropping_cluster = pygame.sprite.RenderUpdates()

        num_empty_cols = 0
        for col in range(self.num_columns):
            if num_empty_cols:
                drop_horizontally(col, num_empty_cols)
            num_empty_cols += drop_vertically(col)

        if self.dropping_cluster:
            for ball in self.dropping_cluster.sprites():
                self.balls[ball.col][ball.row] = None
        else:
            self.stop_dropping_balls()

    def stop_dropping_ball(self, ball):
        self.balls[ball.col][ball.row] = ball

        self.dropping_cluster.remove(ball)
        self.dropped_cluster.add(ball)
        if not self.dropping_cluster:
            self.stop_dropping_balls()

    def stop_dropping_balls(self):
        self.dropping_cluster = None
        self.cluster_balls()
        self.block_events = False

    def get_final_score(self):
        n = len(self.all_balls)
        cleanup_score = 0
        if n == 0:
            cleanup_score = 100
        return self.score - n * (n - 1) + cleanup_score


class SameBallApp(object):

    # In order not to waste CPU resizing images while the user is manually
    # resizing the window, we delay the actual resize until the user activity
    # stops.
    RESIZE_DELAY_MS = 100
    DRAW_DELAY_MS = 1

    MAX_FPS = 60
    MAX_CPU_LOAD = 0.5

    def __init__(self):
        self.init_ui()
        Ball.load_images()

        self.num_colors = 4
        self.num_columns = 10
        self.num_rows = 7

        self.on_game_new()

    def init_ui(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file('same-ball.glade')
        self.builder.connect_signals(self)

        self.window = self.builder.get_object('main_window')
        self.window.show_all()
        self.window.connect('delete-event', self.on_quit)

        self.game_area = self.builder.get_object('game_area')
        self.game_area.modify_bg(Gtk.StateType.NORMAL, BG_COLOR)
        self.game_area.realize()
        os.putenv('SDL_WINDOWID', str(self.game_area.get_window().get_xid()))
        Gdk.flush()

        self.status_bar = self.builder.get_object('status_bar')

        pygame.init()
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()),
                                 pygame.DOUBLEBUF, 0)
        self.screen = pygame.display.get_surface()

        self.update_cb = None
        self.update_duration_s = 1 / SameBallApp.MAX_FPS
        self.resize_cb = None
        self.draw_cb = None
        self.draw_rects = []

        window = self.game_area.get_window()
        window.set_events(window.get_events() |
                          Gdk.EventMask.POINTER_MOTION_MASK |
                          Gdk.EventMask.LEAVE_NOTIFY_MASK |
                          Gdk.EventMask.BUTTON_PRESS_MASK)
        self.game_area.connect('draw', self.on_draw)
        self.game_area.connect('size-allocate', self.on_resize)
        self.game_area.connect('motion-notify-event', self.on_mouse_move)
        self.game_area.connect('leave-notify-event', self.on_mouse_leave)
        self.game_area.connect('button-press-event', self.on_mouse_click)

    def run(self):
        self.board.show()
        pygame.display.update()
        Gtk.main()

    def show_score(self):
        if self.board.has_clusters:
            message = "{} points".format(self.board.score)
        else:
            message = "Game over.  Final score: {} points".format(
                    self.board.get_final_score())
        self.status_bar.push(0, message)

    def schedule_update(self):
        if self.update_cb:
            return

        if self.board.has_updates():
            update_delay_ms = int(max(
                    self.update_duration_s / SameBallApp.MAX_CPU_LOAD * 1000,
                    1000 / SameBallApp.MAX_FPS))
            self.update_cb = GObject.timeout_add(update_delay_ms, self.update)
        else:
            self.show_score()

    def update(self):
        self.update_cb = None
        pygame.display.update(self.board.update())
        self.update_duration_s = time.time() - self.board.t
        self.schedule_update()
        return False

    def on_draw(self, widget, context=None):
        # HACK HACK HACK HACK HACK HACK HACK
        # We'd normally just re-draw the damaged area here, but for some reason
        # (interaction between pygame and pygtk? bad interaction with the
        # window manager? cosmic radiation? bad karma?), the updated area just
        # gets cleared to the background color right after this callback.  So,
        # instead of drawing now, we just schedule a redraw 1ms from now, after
        # that rogue clearing took place.
        # HACK HACK HACK HACK HACK HACK HACK
        if self.draw_cb:
            GObject.source_remove(self.draw_cb)
        ok, rect = Gdk.cairo_get_clip_rectangle(context)
        self.draw_rects.append(
                pygame.Rect(rect.x, rect.y, rect.width, rect.height))
        self.draw_cb = GObject.timeout_add(
                SameBallApp.DRAW_DELAY_MS, self.draw)

    def draw(self):
        self.board.show()
        if self.draw_rects:
            pygame.display.update(self.draw_rects)
        else:
            pygame.display.update()

        self.draw_cb = None
        del self.draw_rects[:]
        return False

    def on_mouse_move(self, widget, event=None):
        if self.board.block_events:
            return

        ball = self.board.ball_at(event.x, event.y)
        if not ball:
            self.board.stop_spinning_cluster()
            return

        if ball.state == Ball.STATE_SPIN:
            return

        self.board.stop_spinning_cluster()
        if len(ball.cluster) > 1:
            self.board.start_spinning_cluster(ball.cluster)

        self.schedule_update()

    def on_mouse_leave(self, widget, event=None):
        self.board.stop_spinning_cluster()
        self.schedule_update()

    def on_mouse_click(self, widget, event=None):
        if self.board.block_events:
            return

        ball = self.board.ball_at(event.x, event.y)
        if not ball:
            return
        if ball.state == Ball.STATE_SPIN:
            self.board.kill_spinning_cluster()
            self.show_score()
        self.schedule_update()

    def on_resize(self, widget, event=None):
        if self.resize_cb:
            GObject.source_remove(self.resize_cb)
        self.resize_cb = GObject.timeout_add(
                SameBallApp.RESIZE_DELAY_MS, self.resize)

    def resize(self):
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()), 0, 0)
        self.board.resize()
        self.board.show()
        pygame.display.update()

        self.resize_cb = None
        return False

    def on_quit(self, widget, data=None):
        Gtk.main_quit()

    def on_game_new(self, widget=None, data=None):
        self.board = Board(self.screen, self.num_colors, self.num_columns, self.num_rows)
        self.show_score()
        self.draw()

    def on_game_size(self, widget, data=None):
        if not widget.get_active():
            return

        name = Gtk.Buildable.get_name(widget)
        if name == 'small_menu_item':
            self.num_columns = 6
            self.num_rows = 5
        elif name == 'medium_menu_item':
            self.num_columns = 10
            self.num_rows = 7
        elif name == 'large_menu_item':
            self.num_columns = 15
            self.num_rows = 10

        self.on_game_new()

    def on_game_difficulty(self, widget, data=None):
        if not widget.get_active():
            return

        name = Gtk.Buildable.get_name(widget)
        if name == 'colors3_menu_item':
            self.num_colors = 3
        elif name == 'colors4_menu_item':
            self.num_colors = 4
        elif name == 'colors5_menu_item':
            self.num_colors = 5
        elif name == 'colors6_menu_item':
            self.num_colors = 6

        self.on_game_new()


if __name__ == '__main__':
    app = SameBallApp()
    app.run()
