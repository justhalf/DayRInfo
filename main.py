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
import wikitextparser as WTP
import requests
import json
from functools import lru_cache
import time

logging.basicConfig(level=logging.INFO)

CLIENT_ID = '839181905249304606'
PUBLIC_KEY = '8e3a6e541e5954298dc0087903037ef6d7c5480d599f2ae8c25d796af4e6ac25'
TOKEN = None

NS_IN_S = 1_000_000_000

# The max number of items to cache
WIKI_CACHE_LIMIT = 50

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
        """Get the id of this map controller"""
        if self.mlat:
            return f'm{-self.mlat}_{self.mlng}'
        else:
            return f'{-self.clat}_{self.clng}'

    @staticmethod
    def from_match(match):
        """Create an instance of a map controller based on the regex match object"""
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
        """Returns the world map image

        This method caches the result the first time it is called.
        """
        if cls.map_image is None:
            with open(str(Path(RES_PATH, cls.map_path)), 'rb') as infile:
                cls.map_image = Image.open(infile).convert('RGBA')
        return cls.map_image

    @classmethod
    def get_marker_image(cls):
        """Returns the marker image

        This method caches the result the first time it is called.
        """
        if cls.marker_image is None:
            with open(str(Path(RES_PATH, cls.marker_path)), 'rb') as infile:
                cls.marker_image = Image.open(infile).convert('RGBA').resize((32, 32))
        return cls.marker_image

client = discord.Client()

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

class Controller:
    # The list of supported commands, mapped to its description
    commands = {
            'help': ('', '\U00002753 Show this help', True, 0),
            'recipe': ('itemName', '\U0001F4DC Show the recipe for the specified item', True, 10),
            'info': ('itemName', '\U0001F50D Show the infobox for the specified item', True, 10),
            'snapshot': ('("world") lat lng (zoom)', '\U0001F4F8 Show a snapshot of the map at the specified location and zoom.\n\tIf "world" is specified (without quotes) the world map is also shown', True, 60),
            'echo': ('text', '\U0001F524 Return back your text', False, 0),
            'clear_cache': ('', '\U0001F9F9 Clear the cache', False, 0),
            }

    # The regex to detect messages starting with a mention to this bot
    KEY_REGEX = f'^(<@[!&]?{CLIENT_ID}>).*$'

    # The URL to wiki API
    WIKI_API_URL = 'https://dayr.fandom.com/api.php?action=query&prop=revisions&rvprop=content&format=json&rvslots=main&titles='

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

    @staticmethod
    def is_enabled(command):
        """Returns True if the command exists and is enabled"""
        if command not in Controller.commands:
            return False
        return Controller.commands[command][2]

    def __init__(self):
        """Defines a controller for direct command to the bot
        """
        # For each user and command, specifies the time the user is able to use that command
        self.user_limit = {}
        for command, (_, _, _, delay) in Controller.commands.items():
            if delay == 0:
                # Not rate-limited
                continue
            self.user_limit[command] = {}
            self.user_limit[command]['delay'] = delay

    def is_trusted(self, author):
        """Returns whether the author is a trusted user
        """
        if author.id == None or 'Verification Tier Level 2' in [role.name for role in author.roles]:
            return True
        return False

    def can_execute(self, msg, command, now):
        """Returns whether the author of the message is allowed to run the command
        """
        if command not in self.user_limit:
            return True, 0
        expiry = self.user_limit[command].get(msg.author.id, 0)
        return now > expiry, expiry-now

    @lru_cache(maxsize=WIKI_CACHE_LIMIT)
    def get_wikitext(self, item):
        """Returns the wikitext of the specified item.

        This method handles redirects as well.
        """
        item = item.strip()
        url = Controller.WIKI_API_URL + item
        response = requests.get(url).text
        try:
            pages = json.loads(response)['query']['pages']
            key = list(pages.keys())[0]
            if key == '-1':
                raise ValueError('Page not found')
            wikitext = pages[key]['revisions'][0]['slots']['main']['*']
            while wikitext.startswith('#REDIRECT'):
                item = wikitext.split(' ', maxsplit=1)[1][2:-2]
                url = Controller.WIKI_API_URL + item
                response = requests.get(url).text
                pages = json.loads(response)['query']['pages']
                key = list(pages.keys())[0]
                wikitext = pages[key]['revisions'][0]['slots']['main']['*']
            return wikitext
        except ValueError as e:
            raise
        except Exception as e:
            logging.info(response)
            logging.error(e)
            return None

    async def execute(self, msg, command, args, sudo=False):
        """Entry point for any direct command
        """
        if not sudo and not Controller.is_enabled(command):
            await self.not_found(msg, command)
            return
        now = time.time_ns()
        can_execute, delay = self.can_execute(msg, command, now)
        if can_execute:
            if command in self.user_limit:
                if self.is_trusted(msg.author):
                    delay = 5 * NS_IN_S
                else:
                    delay = self.user_limit[command]['delay'] * NS_IN_S
                self.user_limit[command][msg.author.id] = now + delay
            await self.__getattribute__(command)(msg, args)
        else:
            await msg.channel.send(**{
                'content': f'You can only use this command in {delay // NS_IN_S} more seconds',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            

    async def recipe(self, msg, item):
        """Replies the user with the crafting recipe of the given item
        """
        try:
            wikitext = self.get_wikitext(item)
        except ValueError as e:
            # Means the page is not found
            return
        for template in WTP.parse(wikitext).templates:
            if template.name == 'Recipe':
                args = template.arguments
                logging.info(args)
                ingredients = []
                tools = []
                def parse_args(args):
                    idx = 0
                    while idx < len(args):
                        arg = args[idx].string.strip(' |')
                        if arg == '':
                            idx += 1
                            continue
                        if '=' not in arg:
                            amount = int(args[idx+1].string.strip(' |'))
                            if amount > 0:
                                ingredients.append(f'{arg.capitalize()} x{amount}')
                            else:
                                ingredients.append(f'{arg.capitalize()}')
                            idx += 1
                        elif arg.startswith('Tool'):
                            tools.append(arg.split('=', maxsplit=1)[1].strip().capitalize())
                        elif arg.startswith('input'):
                            templates = WTP.parse(arg.split('=', maxsplit=1)[1].strip()).templates
                            if len(templates) > 0:
                                parse_args(templates[0].arguments)
                        idx += 1
                parse_args(args)
                ingredients = '• '+'\n• '.join(ingredients)
                tools = '• '+'\n• '.join(tools) if tools else ''
                content = f'To craft {item}, you need:\n{ingredients}'
                if tools:
                    content = f'{content}\nAnd these tools:\n{tools}'
                await msg.channel.send(**{
                    'content': content,
                    'reference': msg.to_reference(),
                    'mention_author': True,
                    })
                return

    def is_infobox(self, name):
        """Returns True if the template name is a type of infobox
        """
        if name.lower().startswith('infobox'):
            return True
        if name == 'Armors_(NEW)':
            return True
        if name == 'All_inclusive_infobox_2020':
            return True
        if name == 'Item':
            return True
        return False

    async def info(self, msg, item):
        """Replies the user with the information from infobox of the specified item
        """
        try:
            wikitext = self.get_wikitext(item)
        except ValueError as e:
            # Means the page is not found
            return
        contents = []
        template_names = []
        for template in WTP.parse(wikitext).templates:
            template_names.append(template.name)
            if self.is_infobox(template.name):
                args = template.arguments
                title = item
                entries = {}
                for arg in args:
                    k, v = arg.string.strip(' |\n').split('=')
                    k = k.strip()
                    v = v.strip()
                    if k.lower() in ['title1', 'name']:
                        # Set this as the item name
                        title = v
                    elif k.lower() in ['image1', 'image'] or not v:
                        # Skip images and empty values
                        continue
                    else:
                        entries[k] = v.replace('\n\n', '\n').replace('\n', '\n\t')
                entries = [f'{k} = {v}' for k, v in entries.items()]
                entries = '• '+'\n• '.join(entries)
                content = f'## **{title}** ##\n{template.name.strip()}\n{entries}'
                contents.append(content)
        logging.info(f'Templates at {item}: '+', '.join(template_names))
        await msg.channel.send(**{
            'content': '\n===\n'.join(contents),
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def snapshot(self, msg, args):
        """Replies the user with a snapshot of the specified location
        """
        args = args.split()
        if args[0] == 'world':
            include_world = True
            args.pop(0)
        else:
            include_world = False
        if len(args) == 2:
            lat, lng = map(float, args)
            zoom = 0
        elif len(args) == 3:
            lat, lng, zoom = map(float, args)
        map_controller = MapController(lat, lng, zoom)
        image = map_controller.generate_snapshot(include_world=include_world)
        snapshot_id = map_controller.get_id().replace('_', ', ')
        location_str = f'center at -{snapshot_id}'
        content = f'Here is a snapshot of that location ({location_str}).'
        await msg.channel.send(**{
            'content': content,
            'file': discord.File(image, filename=f'snapshot_{map_controller.get_id()}.png'),
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def help(self, msg, args=None, intro=None):
        """Replies the user with the help message
        """
        if intro is not None:
            intro = f'{intro.strip()} '
        else:
            intro = ''
        content = f'{intro}I understand the following commands (tag me at the start of the message):\n'
        for command, (args, desc, enabled, delay) in Controller.commands.items():
            if not enabled:
                continue
            if args:
                args = f' {args.strip()}'
            if desc:
                desc = f'\n\t{desc}'
            content = f'{content}`@DayRInfo {command}{args}`{desc}\n'
        content = f'{content}----------\n'
        content = f'{content}• Also, if you tag me on a message containing a link to the interactive Day R map \U0001F5FA with a location URL, I will send you a snapshot of the location.\n'
        content = f'{content}• React with \U0000274C to any of my messages to delete it (if I still remember that it was my message)'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def not_found(self, msg, command):
        """Replies the user with the help message, prepended with the information about invalid command
        """
        await self.help(msg, intro=f'I do not understand `{command}`.')

    ### Below are private functions

    async def echo(self, msg, args):
        """Replies the user with their own message
        """
        await msg.channel.send(**{
            'content': args,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def clear_cache(self, msg, args):
        """Clears the cache
        """
        self.get_wikitext.cache_clear()
        await msg.channel.send(**{
            'content': 'Cache cleared',
            })

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
    if message.author.id == None and message.channel.type == discord.ChannelType.private:
        # Give the bot creator access to more commands
        sudo = True
    else:
        sudo = False

    logging.info(f'Received message: {message.content} from {message.author} at {message.created_at}')
    intent = get_intent(message)
    logging.info(f'Intent: {intent}')
    if intent == Intent.DIRECT:
        command, args = controller.get_args(message)
        logging.info(f'Command: {command}, args: {args}')
        await controller.execute(message, command, args, sudo)
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
    #     await controller.help(message, intro='I see you are calling me.')

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

