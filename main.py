# -*- coding: utf-8 -*-
"""
Discord bot for Day R Survival game
"""
from __future__ import print_function, division
__author__ = 'Aldrian Obaja Muis'
__date__ = '2021-05-05'

# Import statements
import sys
from argparse import ArgumentParser
import discord
import logging
import os
import re
from PIL import Image, ImageDraw
from pathlib import Path
from io import BytesIO
from asyncio import create_task as run

logging.basicConfig(level=logging.INFO)

CLIENT_ID = '839181905249304606'
PUBLIC_KEY = '8e3a6e541e5954298dc0087903037ef6d7c5480d599f2ae8c25d796af4e6ac25'
TOKEN = None

class Intent:
    DIRECT = 'Direct'
    MAP = 'Map'
    NONE = 'None'

def get_intent(msg):
    """Returns the intent of the message, as defined by the Intent class
    """
    if re.search(MapController.MAP_REGEX, msg.content) and client.user.id in msg.raw_mentions:
        return Intent.MAP
    elif re.match(Controller.KEY_REGEX, msg.content):
        return Intent.DIRECT
    else:
        return Intent.NONE

RES_PATH = 'res'

class MapController:
    """The regex recognizing URL to the interactive Day R map"""
    MAP_REGEX = 'https://dayr-map.info/(?:index\.html)?\?(?:start\=true&)?clat\=([-0-9.]+)&clng\=([-0-9.]+)(?:&mlat\=([-0-9.]+)&mlng\=([-0-9.]+))?&zoom\=([-0-9.]+)'

    """Stores the image of the world map"""
    map_image = None
    map_path = 'world_map_biomes_cities.png'

    """Stores the image of the marker"""
    marker_image = None
    marker_path = 'marker_event.png'

    """Controller for messages containing URL to the interactive Day R map
    """
    def __init__(self, clat, clng, zoom, mlat=None, mlng=None):
        self.clat = clat
        self.clng = clng
        self.zoom = zoom
        self.mlat = mlat
        self.mlng = mlng
        self.has_marker = self.mlat is not None

    def __repr__(self):
        return f'clat: {self.clat}, clng: {self.clng}, mlat: {self.mlat}, mlng: {self.mlng}, zoom: {self.zoom}'

    __str__ = __repr__

    def generate_snapshot(self, include_world=True):
        """Generate a snapshot for this location.

        include_world: If True, will include the world map at the bottom as the bigger picture
        """
        if self.has_marker:
            y, x = -self.mlat, self.mlng
        else:
            y, x = -self.clat, self.clng
        zoom = self.zoom
        world = MapController.get_world_image()
        top, bottom = y - 256/(2**zoom), y + 256/(2**zoom)
        left, right = x - 256/(2**zoom), x + 256/(2**zoom)
        logging.info(f'Cropping world at {left} {top} {right} {bottom}')
        snapshot = world.crop((left, top, right, bottom))
        if top - bottom <= 256:
            snapshot = snapshot.resize((256, 256), resample=Image.NEAREST)
        else:
            snapshot = snapshot.resize((256, 256), resample=Image.BILINEAR)

        if self.has_marker:
            marker = MapController.get_marker_image()
            snapshot.paste(marker, (112, 96), marker.getchannel('A'))

        if include_world:
            # Expand the canvas and put the world map under the inset
            result = Image.new('RGBA', (256, 400))
            result.paste(snapshot)
            result.paste(world.resize((256, 144)), (0, 256))

            # Draw a marker at the same place at the world map
            if self.has_marker:
                result.paste(marker, (int(x//32)-16, int(y//32)-32+256), marker.getchannel('A'))

            # Draw an overlay indicating the inset on the world map
            overlay = Image.new('RGBA', (256, 400))
            draw = ImageDraw.Draw(overlay)
            fill_color = (255, 255, 0, 64) # Transparent yellow
            outline_color = (255, 255, 0, 96) # More solid yellow
            draw.rectangle((max(0, int(left//32)),
                            max(0, int(top//32))+256,
                            min(256, int(right//32)),
                            min(144, int(bottom//32))+256),
                           fill=fill_color,
                           outline=outline_color,
                           width=1)
            draw.line((0, 256, max(0, int(left//32)), min(144, int(bottom//32))+256), (255, 255, 0, 96), 1)
            draw.line((256, 256, min(256, int(right//32)), min(144, int(bottom//32))+256), (255, 255, 0, 96), 1)
            result = Image.alpha_composite(result, overlay)
        else:
            result = snapshot
        
        output = BytesIO()
        result.save(output, format='png')
        output.seek(0)
        return output

    def get_id(self):
        if self.mlat:
            return f'm{-self.mlat}_{self.mlng}'
        else:
            return f'{-self.clat}_{self.clng}'

    @staticmethod
    def from_match(match):
        clat = float(match.group(1))
        clng = float(match.group(2))
        if match.group(3):
            mlat = float(match.group(3))
            mlng = float(match.group(4))
        else:
            mlat = mlng = None
        zoom = float(match.group(5))
        return MapController(clat, clng, zoom, mlat, mlng)

    @classmethod
    def get_world_image(cls):
        if cls.map_image is None:
            with open(str(Path(RES_PATH, cls.map_path)), 'rb') as infile:
                cls.map_image = Image.open(infile).convert('RGBA')
        return cls.map_image

    @classmethod
    def get_marker_image(cls):
        if cls.marker_image is None:
            with open(str(Path(RES_PATH, cls.marker_path)), 'rb') as infile:
                cls.marker_image = Image.open(infile).convert('RGBA').resize((32, 32))
        return cls.marker_image

client = discord.Client()

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

class Controller:
    """The list of supported commands, mapped to its description"""
    commands = {
            'help': ('', '\U00002753 Show this help'),
            'echo': ('text', '\U0001F524 Return back your text'),
            }

    KEY_REGEX = f'^(<@!?{CLIENT_ID}>).*$'

    @staticmethod
    def get_args(msg):
        """Parse the message which has been determined to have DIRECT intent
        """
        match = re.match(Controller.KEY_REGEX, msg.content)
        full_command = msg.content[match.end(1):].strip().split(' ', maxsplit=1)
        if len(full_command) == 1:
            command = full_command[0]
            if not command:
                command = 'help'
            args = None
        else:
            command = full_command[0]
            args = full_command[1]
        return command, args

    def __init__(self):
        pass

    async def execute(self, msg, command, args):
        if command not in Controller.commands:
            await self.not_found(msg, command)
            return
        await self.__getattribute__(command)(msg, args)

    async def echo(self, msg, args):
        await msg.channel.send(**{
            'content': args,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def help(self, msg, intro=None):
        if intro is not None:
            intro = f'{intro.strip()} '
        else:
            intro = ''
        content = f'{intro}I understand the following commands (tag me at the start of the message):\n'
        for command, (args, desc) in Controller.commands.items():
            if args:
                args = f' {args.strip()}'
            if desc:
                desc = f'\n\t{desc}'
            content = f'{content}`@DayRInfo {command}{args}`{desc}\n'
        content = f'{content}• Also, if you tag me on a message containing a link to the interactive Day R map \U0001F5FA with a location URL, I will send you a snapshot of the location.\n'
        content = f'{content}• React with \U0000274C to any of my messages to delete it (if I still remember that it was my message)'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def not_found(self, msg, command):
        await self.help(msg, f'I do not understand `{command}`.')

controller = Controller()

@client.event
async def on_reaction_add(reaction, user):
    if reaction.message.author == client.user and reaction.message.reference.cached_message.author == user and reaction.emoji == '\U0000274C':
        await reaction.message.delete()

@client.event
async def on_message(message):
    if message.author == client.user:
        # If this is our own (the bot's) message, ignore it
        return

    logging.info(f'Received message: {message.content} from {message.author} at {message.created_at}')
    intent = get_intent(message)
    logging.info(f'Intent: {intent}')
    if intent == Intent.DIRECT:
        command, args = controller.get_args(message)
        logging.info(f'Command: {command}, args: {args}')
        await controller.execute(message, command, args)
    elif intent == Intent.MAP:
        matches = re.finditer(MapController.MAP_REGEX, message.content)
        for idx, match in enumerate(matches):
            map_controller = MapController.from_match(match)
            logging.info(f'Generating image for {map_controller}')
            image = map_controller.generate_snapshot()
            snapshot_id = map_controller.get_id().replace('_', ', ')
            if snapshot_id[0] == 'm':
                location_str = f'marker at -{snapshot_id[1:]}'
            else:
                location_str = f'center at -{snapshot_id}'
            if idx == 0:
                content = f'Here is a snapshot of that location ({location_str}).'
            else:
                content = ''
            await message.channel.send(**{
                'content': content,
                'file': discord.File(image, filename=f'snapshot_{map_controller.get_id()}.png'),
                'reference': message.to_reference(),
                'mention_author': True,
                })
        run(message.add_reaction('\U0001F5FA')) # map emoji
    # elif intent == Intent.NONE and client.user.id in message.raw_mentions:
    #     await controller.help(message, 'I see you are calling me.')

def main(args=None):
    parser = ArgumentParser(description='')
    parser.add_argument('--token_path', default='token.txt',
                        help='The path to the token')
    args = parser.parse_args(args)
    token_path = args.token_path
    try:
        with open(token_path, 'r') as infile:
            TOKEN = infile.read().strip()
    except:
        TOKEN = os.environ.get('TOKEN')
    client.run(TOKEN)

if __name__ == '__main__':
    main()

