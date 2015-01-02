#!/usr/bin/python

from __future__ import division

import math
import pygame
import random
import re

EPSILON = 1e-6


class Point(object):
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def radius(self):
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def scale(self, f):
        self.x *= f
        self.y *= f
        self.z *= f
        return self

    def normalize(self):
        r = self.radius()
        if r < EPSILON:
            return self
        return self.scale(1/r)

    def dot_product(self, other):
        return (self.x * other.x +
                self.y * other.y +
                self.z * other.z)

    def rotate_y(self, angle):
        return Point(self.z * math.cos(angle) - self.x * math.sin(angle),
                     self.y,
                     self.z * math.sin(angle) + self.x * math.cos(angle))

    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y, self.z + other.z)
    def __sub__(self, other):
        return Point(self.x - other.x, self.y - other.y, self.z - other.z)

    def __str__(self):
        return '({:.2f}, {:.2f}, {:.2f})'.format(self.x, self.y, self.z)


def random_unit_vector():
    while True:
        pt = Point(random.random()*2 - 1,
                   random.random()*2 - 1,
                   random.random()*2 - 1)
        r = pt.radius()
        if r >= EPSILON and r < 1.0:
            return pt.normalize()


class PerlinGrid(object):

    def __init__(self, size):
        self.grid = [[[random_unit_vector()
                       for i in range(size)]
                      for j in range(size)]
                     for k in range(size)] 

    def eval_at(self, pt):
        # Scale from [-1,1] to [0, GRID_SIZE-1).
        x = (pt.x + 1)/2 * (len(self.grid) - 1)
        y = (pt.y + 1)/2 * (len(self.grid[0]) - 1)
        z = (pt.z + 1)/2 * (len(self.grid[0][0]) - 1)

        def interpolate(v0, v1, f):
            return v0*(1-f) + v1*f

        def s_curve(f):
            # http://www.noisemachine.com/talk1/java/noisegrid.html
            f = math.fabs(f)
            return 3*(f**2) - 2*(f**3)

        def value_at(i, j, k):
            dist_vec = Point(x, y, z) - Point(i, j, k)
            return dist_vec.dot_product(self.grid[i][j][k])

        (i, j, k) = (int(x), int(y), int(z))

        (fx, fy, fz) = (s_curve(x - i), s_curve(y - j), s_curve(z - k))

        return interpolate(
                interpolate(
                    interpolate(
                        value_at(i  , j  , k  ),
                        value_at(i+1, j  , k  ),
                        fx),
                    interpolate(
                        value_at(i  , j+1, k  ),
                        value_at(i+1, j+1, k  ),
                        fx),
                    fy),
                interpolate(
                    interpolate(
                        value_at(i  , j  , k+1),
                        value_at(i+1, j  , k+1),
                        fx),
                    interpolate(
                        value_at(i  , j+1, k+1),
                        value_at(i+1, j+1, k+1),
                        fx),
                    fy),
                fz)


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


class Color(object):
    HEXCOLOR_RE = re.compile(r'^#?([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$')

    @staticmethod
    def hex(rgb):
        m = Color.HEXCOLOR_RE.match(rgb)
        if not m:
            return Color(0, 0, 0, 0)
        return Color(int(m.group(1), 16),
                     int(m.group(2), 16),
                     int(m.group(3), 16))

    def __init__(self, r, g, b, a=255):
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    def __add__(self, other):
        return Color(self.r + other.r,
                     self.g + other.g,
                     self.b + other.b,
                     self.a)

    def __mul__(self, f):
        return Color(self.r * f,
                     self.g * f,
                     self.b * f,
                     self.a)

    def combine(self, other, alpha):
        return self * (1 - alpha) + other * alpha

    def to_pygame_color(self):
        return pygame.Color(clamp(int(self.r), 0, 255),
                            clamp(int(self.g), 0, 255),
                            clamp(int(self.b), 0, 255),
                            clamp(int(self.a), 0, 255))


class MarbleTexture(object):

    def __init__(self, perlin_grid_size):
        self.perlin1 = PerlinGrid(perlin_grid_size)
        self.perlin2 = PerlinGrid(perlin_grid_size*2)
        self.perlin3 = PerlinGrid(perlin_grid_size*4)
        self.perlin4 = PerlinGrid(perlin_grid_size*8)
        self.perlin5 = PerlinGrid(perlin_grid_size*16)
        self.alpha_y = 0

    def rotate(self, alpha_y):
        self.alpha_y = alpha_y

    def at(self, pt):
        """pt is a point in the [-1,1] cube"""

        pt = pt.rotate_y(self.alpha_y)
        noise = (self.perlin1.eval_at(pt) +
                 self.perlin2.eval_at(pt) * 0.5 +
                 self.perlin3.eval_at(pt) * 0.25 +
                 self.perlin4.eval_at(pt) * 0.125 +
                 self.perlin5.eval_at(pt) * 0.0625)
        
        return int((math.sin((pt.x + noise) * 4 * math.pi) + 1.0) * 127)


class Marble(object):

    def __init__(self, viewer_z, screen_z, perlin_grid_size):
        self.viewer_z = viewer_z
        self.screen_z = screen_z
        self.texture = MarbleTexture(perlin_grid_size)
#        self.gradient = [Color.hex('#0b3421'), Color.hex('#57ab47')]  # Green.
#        self.gradient = [Color.hex('#240404'), Color.hex('#ab1717')]  # Red.
#        self.gradient = [Color.hex('#101044'), Color.hex('#3737db')]  # Blue.
#        self.gradient = [Color.hex('#6e3b07'), Color.hex('#ffb422')]  # Yellow.
        self.gradient = [Color.hex('#140414'), Color.hex('#8b27bb')]  # Purple.
#        self.gradient = [Color.hex('#141414'), Color.hex('#999999')]  # White.
        self.ambient_light_pt = Point(-1, -1, .5).normalize()
        self.spotlight_pt = Point(-1, -1, 2).normalize()

    def gradient_at(self, v):
        return self.gradient[0].combine(self.gradient[1], v / 255)

    def ambient_light_at(self, pt):
        v = self.ambient_light_pt.dot_product(pt)
        return v + .8

    def specular_ligth_at(self, pt):
        v = self.spotlight_pt.dot_product(pt)
        u = v**20 * 1500
        return Color(u, u, u)

    def trace_ray(self, screen_x, screen_y):
        # http://en.wikipedia.org/wiki/Line%E2%80%93sphere_intersection
        line_orig = Point(0, 0, self.viewer_z)
        line_dir = (Point(screen_x, screen_y, self.screen_z) - line_orig).normalize()
        sphere_orig = Point(0, 0, 0)
        sphere_r = 0.9
        
        rel_orig = line_orig - sphere_orig
        delta = (line_dir.dot_product(rel_orig)**2 -
                 rel_orig.radius()**2 +
                 sphere_r**2)
        if delta < 0:
            return None
        
        d = -line_dir.dot_product(rel_orig) - math.sqrt(delta)
        return line_orig + line_dir.scale(d)

    def at(self, screen_x, screen_y):
        pt = self.trace_ray(screen_x, screen_y)
        if not pt:
            return pygame.Color(0, 0, 0, 0)

        v = self.texture.at(pt)
        color = self.gradient_at(v) * self.ambient_light_at(pt) + self.specular_ligth_at(pt)

        return color.to_pygame_color()

    def rotate(self, alpha_y):
        self.texture.rotate(alpha_y)


def main():
    WINDOW_WIDTH = 200
    WINDOW_HEIGHT = 200
    ROTATION_DURATION_S = 3
    MAX_FPS = 10
    NUM_FRAMES = ROTATION_DURATION_S * MAX_FPS

    marble = Marble(viewer_z=9, screen_z=1, perlin_grid_size=3)

    def draw_frame(angle, surface, ox, oy):
        marble.rotate(angle)
        surface.lock()
        for x in range(WINDOW_WIDTH):
            for y in range(WINDOW_HEIGHT):
                color = marble.at((x*2 - WINDOW_WIDTH)/WINDOW_WIDTH,
                                  (y*2 - WINDOW_HEIGHT)/WINDOW_HEIGHT)
                surface.set_at((ox+x, oy+y), color)
        surface.unlock()

    def animate():
        pygame.display.init()
        clock = pygame.time.Clock()
        screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))

        i = 0
        while 1:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        return

            draw_frame(i * 2*math.pi / NUM_FRAMES, screen, 0, 0)

            i = (i + 1) % NUM_FRAMES
            pygame.display.flip()
            clock.tick(MAX_FPS)

    def render():
        surf = pygame.Surface((NUM_FRAMES*WINDOW_WIDTH, WINDOW_HEIGHT),
                              depth=32, flags=pygame.SRCALPHA)
        for i in range(NUM_FRAMES):
            print "Frame {} of {}".format(i, NUM_FRAMES)
            draw_frame(i * 2*math.pi / NUM_FRAMES, surf, i*WINDOW_WIDTH, 0)
        pygame.image.save(surf, "purple.png")

    render()

if __name__ == '__main__':
    main()
