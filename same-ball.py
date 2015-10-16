#!/usr/bin/python3
#
# Copyright 2015 David Lazăr
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import GdkX11
from gi.repository import Gtk
import base64
import csv
import gettext
import hashlib
import math
import os
import pygame
import random
import re
import struct
import time
import xdg.BaseDirectory

APP_DIR = 'same-ball'
TRANSLATION_DOMAIN = 'same-ball'

BG_COLOR = Gdk.RGBA()
BG_COLOR.parse('#202026')

gettext.install(TRANSLATION_DOMAIN, names=['ngettext'])


def generate_game_seed():
    return base64.b32encode(hashlib.sha256(
        struct.pack('!d', time.time())).digest()[:5])


def to_pygame(gdk_color):
    return (int(gdk_color.red * 255),
            int(gdk_color.green * 255),
            int(gdk_color.blue * 255))


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
        Ball.IMAGES = [pygame.image.load(os.path.join('data', f))
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
        self.num_colors = num_colors
        self.num_columns = num_columns
        self.num_rows = num_rows

        self.game_seed = game_seed or generate_game_seed()
        random.seed(base64.b32decode(self.game_seed, casefold=True))

        Ball.init(self.num_colors)
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
            raise RuntimeError('Board.kill_spinning_cluster() called unexpectedly.')

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
            raise RuntimeError('Board.remove_ball() called unexpectedly.')

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
        # Increment Score.VERSION when modifying this function.
        n = len(self.all_balls)
        cleanup_bonus = 0
        if n == 0:
            cleanup_bonus = self.num_columns * self.num_rows * self.num_colors
        return Score.new(self.score + cleanup_bonus,
                         n == 0,
                         '{}×{}'.format(self.num_columns, self.num_rows),
                         self.num_colors)


class Score(object):

    VERSION = 1

    HDR_VERSION = 'version'
    HDR_CLEARED_BOARD = 'cleared-board'
    HDR_POINTS = 'points'
    HDR_BOARD_SIZE = 'board-size'
    HDR_NUM_COLORS = 'num-colors'
    HDR_TIME = 'time'

    CLEARED_BOARD_IMAGE = 'data/cleared-board.png'

    @staticmethod
    def headers():
        return [Score.HDR_VERSION,
                Score.HDR_POINTS,
                Score.HDR_CLEARED_BOARD,
                Score.HDR_BOARD_SIZE,
                Score.HDR_NUM_COLORS,
                Score.HDR_TIME]

    @staticmethod
    def from_values(values):
        return Score(int(values.get(Score.HDR_VERSION, 1)),
                     int(values.get(Score.HDR_POINTS, 0)),
                     (values.get(Score.HDR_CLEARED_BOARD, '') == 'True'),
                     values.get(Score.HDR_BOARD_SIZE, '4×4'),
                     int(values.get(Score.HDR_NUM_COLORS, 4)),
                     int(values.get(Score.HDR_TIME, 0)))

    @staticmethod
    def new(points, cleared_board, board_size, num_colors):
        return Score(Score.VERSION, points, cleared_board, board_size, num_colors,
                     int(time.time()))

    def __init__(self, version, points, cleared_board, board_size, num_colors, time):
        self.version = version
        self.points = points
        self.cleared_board = cleared_board
        self.board_size = board_size
        self.num_colors = num_colors
        self.time = time

    def values(self):
        return [str(self.version),
                str(self.points),
                str(self.cleared_board),
                str(self.board_size),
                str(self.num_colors),
                str(int(self.time))]

    def __lt__(self, other):
        if self.version > other.version: return True
        if self.version < other.version: return False
        if self.points > other.points: return True
        if self.points < other.points: return False
        if self.cleared_board and not other.cleared_board: return True
        if not self.cleared_board and other.cleared_board: return False
        return False

    def points_str(self):
        return ngettext(
                '{num_points} point',
                '{num_points} points',
                self.points).format(num_points=self.points)

    def num_colors_str(self):
        return ngettext(
                '{num_colors} color',
                '{num_colors} colors',
                self.num_colors).format(num_colors=self.num_colors)

    def board_size_str(self):
        board_sizes = {
                '6×5': _('small'),
                '10×7': _('medium'),
                '15×10': _('large'),
        }
        return board_sizes.get(self.board_size, self.board_size)

    def time_str(self):
        return time.strftime('%x', time.localtime(self.time))

    def populate(self, grid, row, bold):
        def attach(widget, column):
            grid.attach(widget, column, row, 1, 1)

        def make_label(message):
            l = Gtk.Label(message)
            if bold:
                l.set_markup('<b>' + GLib.markup_escape_text(message) + '</b>')
            return l

        if self.cleared_board:
            attach(Gtk.Image.new_from_file(Score.CLEARED_BOARD_IMAGE), 0)
        attach(make_label(self.points_str()), 1)
        attach(make_label(self.num_colors_str()), 2)
        attach(make_label(self.board_size_str()), 3)
        attach(make_label(self.time_str()), 4)


class HighScores(object):

    FILE = 'high-scores.csv'
    SIZE = 10

    def __init__(self):
        self.scores = []
        self._load()

    def add(self, score):
        self.scores.append(score)
        i = len(self.scores) - 1
        while i > 0 and self.scores[i-1] > self.scores[i]:
            self.scores[i-1], self.scores[i] = self.scores[i], self.scores[i-1]
            i -= 1
        del self.scores[HighScores.SIZE + 1:]

        self._save()
        return i

    def populate(self, grid, current_score_index):
        grid.foreach(lambda widget: grid.remove(widget))
        for i, score in enumerate(self.scores):
            score.populate(grid, i, i == current_score_index)
        grid.show_all()

    def _load(self):
        def load_from_file(file_name):
            try:
                with open(file_name, newline='', encoding='utf-8') as f:
                    return [Score.from_values(v) for v in csv.DictReader(f)]
            except FileNotFoundError:
                return []

        for path in xdg.BaseDirectory.load_data_paths(APP_DIR):
            self.scores = load_from_file(os.path.join(path, HighScores.FILE))
            if self.scores:
                return True

        return False

    def _save(self):
        file_name = os.path.join(xdg.BaseDirectory.save_data_path(APP_DIR),
                                 HighScores.FILE)
        with open(file_name, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(Score.headers())
            writer.writerows(score.values() for score in self.scores)


class SameBallApp(object):

    # In order not to waste CPU resizing images while the user is manually
    # resizing the window, we delay the actual resize until the user activity
    # stops.
    RESIZE_DELAY_MS = 100
    DRAW_DELAY_MS = 1

    MAX_FPS = 60
    MAX_CPU_LOAD = 0.5

    def __init__(self):
        self.high_scores = HighScores()
        self.init_ui()
        Ball.load_images()

        self.num_colors = 4
        self.num_columns = 10
        self.num_rows = 7

        self.on_game_new()

    def init_ui(self):
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(TRANSLATION_DOMAIN)
        self.builder.add_from_file(os.path.join('data', 'same-ball.glade'))
        self.builder.connect_signals(self)

        self.window = self.builder.get_object('main_window')
        self.window.show_all()
        self.window.connect('delete-event', self.on_quit)

        self.game_area = self.builder.get_object('game_area')
        self.game_area.override_background_color(Gtk.StateFlags.NORMAL, BG_COLOR)
        self.game_area.realize()
        os.putenv('SDL_WINDOWID', str(self.game_area.get_window().get_xid()))
        Gdk.flush()

        self.status_bar = self.builder.get_object('status_bar')
        self.status_bar_context_id = self.status_bar.get_context_id('score')
        self.high_scores_dialog = self.builder.get_object('high_scores_dialog')
        self.high_scores_dialog.set_transient_for(self.window)
        self.game_over_label = self.builder.get_object('game_over_label')
        self.final_score_label = self.builder.get_object('final_score_label')
        self.about_dialog = self.builder.get_object('about_dialog')

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

    def schedule_update(self):
        if self.update_cb:
            return

        if self.board.has_updates():
            update_delay_ms = int(max(
                    self.update_duration_s / SameBallApp.MAX_CPU_LOAD * 1000,
                    1000 / SameBallApp.MAX_FPS))
            self.update_cb = GLib.timeout_add(update_delay_ms, self.update)
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
            GLib.source_remove(self.draw_cb)
        ok, rect = Gdk.cairo_get_clip_rectangle(context)
        self.draw_rects.append(
                pygame.Rect(rect.x, rect.y, rect.width, rect.height))
        self.draw_cb = GLib.timeout_add(
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
            GLib.source_remove(self.resize_cb)
        self.resize_cb = GLib.timeout_add(
                SameBallApp.RESIZE_DELAY_MS, self.resize)

    def resize(self):
        pygame.display.set_mode((self.game_area.get_allocated_width(),
                                 self.game_area.get_allocated_height()), 0, 0)
        self.board.resize()
        self.board.show()
        pygame.display.update()

        self.resize_cb = None
        return False

    def show_score(self):
        if self.game_over:
            return

        if self.board.has_clusters:
            message = ngettext(
                    '{num_points} point',
                    '{num_points} points',
                    self.board.score).format(num_points=self.board.score)
            self.status_bar.pop(self.status_bar_context_id)
            self.status_bar.push(self.status_bar_context_id, message)
        else:
            self.game_over = True
            self.status_bar.pop(self.status_bar_context_id)
            self.on_game_over()

    def on_game_over(self):
        final_score = self.board.get_final_score()
        current_score_index = self.high_scores.add(final_score)

        if len(self.board.all_balls):
            title_message = _('Game over')
            status_message = ngettext(
                    'Game over.  Final score: {num_points} point.',
                    'Game over.  Final score: {num_points} points.',
                    final_score.points).format(num_points=final_score.points)
        else:
            title_message = _('You won!')
            status_message = ngettext(
                    'You won!  Final score: {num_points} point.',
                    'You won!  Final score: {num_points} points.',
                    final_score.points).format(num_points=final_score.points)

        final_score_message = ngettext(
                'Final score: {num_points} point',
                'Final score: {num_points} points',
                final_score.points).format(num_points=final_score.points)

        if current_score_index < HighScores.SIZE:
            self.high_scores_dialog.set_title(title_message)
            self.game_over_label.set_text(title_message)

            self.final_score_label.set_text(final_score_message)
            self.final_score_label.show()

            self.show_high_scores_dialog(current_score_index)
        else:
            self.status_bar.push(self.status_bar_context_id, status_message)

    def show_high_scores_dialog(self, current_score_index=None):
        high_scores_grid = self.builder.get_object('high_scores_grid')
        self.high_scores.populate(high_scores_grid, current_score_index)
        self.high_scores_dialog.show()

    def on_game_high_scores(self, widget, data=None):
        self.game_over_label.set_text(_('High Scores'))
        self.high_scores_dialog.set_title(_('High Scores'))
        self.final_score_label.hide()
        self.show_high_scores_dialog()

    def on_high_scores_ok(self, widget, data=None):
        self.high_scores_dialog.hide()

    def on_help_about(self, widget, data=None):
        self.about_dialog.show()

    def hide_on_delete(self, widget, data=None):
        return widget.hide_on_delete()

    def on_quit(self, widget, data=None):
        Gtk.main_quit()

    def on_game_new(self, widget=None, data=None):
        self.game_over = False
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
