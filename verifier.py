# -*- coding: utf-8 -*-
"""
To recognize the username in an image
"""
from __future__ import print_function, division
__author__ = 'Aldrian Obaja Muis'
__date__ = '2021-12-04'

# Import statements
import sys
from argparse import ArgumentParser
from PIL import ImageFont, ImageDraw, Image
import cv2
import numpy as np
from fontTools.ttLib import TTFont
from itertools import chain

class VerificationStatus:
    INVALID = 'INVALID'
    USERNAME_MISMATCH = 'USERNAME_MISMATCH'
    USERNAME_NOT_SUPPORTED = 'USERNAME_NOT_SUPPORTED'
    VERIFIED = 'VERIFIED'

class Verifier:
    DEFAULT_KEYWORD = 'dayr discord'

    def __init__(self, fontpath, threshold=0.75):
        self.debug = False
        self.threshold = threshold
        self.fonts = {v:ImageFont.truetype(fontpath, size=v) for v in range(74, 79)}
        self.valid_chars = set(chr(o) for table in TTFont(fontpath)['cmap'].tables for o in table.cmap.keys())
        self.keyword_images = {}
        for font_size, font in self.fonts.items():
            keyword_image = draw_text(Verifier.DEFAULT_KEYWORD, font, (255, 255, 255))
            self.keyword_images[font_size] = np.array(keyword_image)
            if self.debug and font_size == 76:
                keyword_image.save('test/keyword_image.png')

    def username_is_supported(self, username):
        """Returns whether the given username is supported by the verifier
        """
        return all(c in self.valid_chars for c in username)

    def verify(self, image, username, keyword=None):
        """Verify whether the given username is found in the image just before the keyword
        """
        if not self.username_is_supported(username):
            return VerificationStatus.USERNAME_NOT_SUPPORTED, 0, 0, 0

        if keyword is not None and keyword != Verifier.DEFAULT_KEYWORD:
            keyword_images = {}
            for font_size, font in self.fonts.items():
                keyword_image = draw_text(keyword, font, (255, 255, 255))
                if self.debug:
                    keyword_image.save('test/keyword_image.png')
                keyword_images[font_size] = np.array(keyword_image)
        else:
            keyword_images = self.keyword_images

        w, h = image.size
        image = image.crop((0, h//2, w//2, h))
        image = np.array(image)
        best_font_size = 0
        best_confidence = 0
        best_y = 0
        best_x = 0
        for font_size, keyword_image in keyword_images.items():
            heat_map = cv2.matchTemplate(image, keyword_image, cv2.TM_CCOEFF_NORMED)
            confidence = np.max(heat_map)
            if confidence >= best_confidence:
                best_confidence = confidence
                best_font_size = font_size
                best_font = self.fonts[best_font_size]
                best_y, best_x = np.unravel_index(np.argmax(heat_map), heat_map.shape)

        username_image = np.array(draw_text(username, best_font, (255, 229, 51)))

        heat_map = cv2.matchTemplate(image, username_image, cv2.TM_CCOEFF_NORMED)
        sub_heat_map = heat_map[best_y-10:best_y+10,:75]
        confidence = np.max(sub_heat_map)

        h, w = username_image.shape[:2]
        y, x = np.unravel_index(np.argmax(sub_heat_map), sub_heat_map.shape)
        y += best_y-10

        if self.debug:
            Image.fromarray(username_image).save('test/username_image.png')
            Image.fromarray(sub_heat_map).save('test/heat_map.tiff')

            cv2.rectangle(image, (x,y), (x+w, y+h), (255, 0, 0, 255), 2)

            image_result = Image.fromarray(image)
            image_result.save('test/result.png')

        result = None
        if best_confidence < self.threshold:
            result = VerificationStatus.INVALID
        elif confidence < self.threshold or abs(x+w-best_x) >= 20:
            result = VerificationStatus.USERNAME_MISMATCH
        else:
            result = VerificationStatus.VERIFIED
        return result, confidence, best_confidence, best_font_size

def draw_text(text, font, color):
    """Draw the text with the specified font and color and return as image
    """
    text_bbox = font.getbbox(text, anchor='la')
    text_size = (text_bbox[2], text_bbox[3])
    text_image = Image.new('RGBA', text_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_image)
    x = 0
    for c in text:
        draw.text((x, 0), c, font=font, fill=color, anchor='la')
        x += font.getlength(c)-1
    text_image.thumbnail((text_size[0]//2, text_size[1]//2))
    return text_image

def main(args=None):
    parser = ArgumentParser(description='')
    parser.add_argument('--imagepath', default='test/justhalf.png')
    parser.add_argument('--fontpath', default='test/freemono.ttf')
    parser.add_argument('--username', default='justhalf')
    parser.add_argument('--keyword', default='dayr discord')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(args)

    imagepath = args.imagepath
    fontpath = args.fontpath
    username = args.username
    keyword = args.keyword
    debug = args.debug

    verifier = Verifier(fontpath)
    if debug:
        verifier.debug = True

    with open(imagepath, 'rb') as infile:
        image = Image.open(infile, 'r').convert('RGBA')

    print(verifier.verify(image, username, keyword))

if __name__ == '__main__':
    main()

