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
from asyncio import create_task as run, sleep
import aiohttp
import wikitextparser as WTP
import json
from functools import wraps
from asyncstdlib import lru_cache
import time
from datetime import datetime, timedelta
from collections import Counter

logging.basicConfig(level=logging.INFO)

# Basic info about this bot
CLIENT_ID = '839181905249304606'
PUBLIC_KEY = '8e3a6e541e5954298dc0087903037ef6d7c5480d599f2ae8c25d796af4e6ac25'
TOKEN = None

NS_IN_S = 1_000_000_000

# The max number of items to cache
WIKI_CACHE_LIMIT = 50

class State:
    """Enumeration of Controller states"""
    NORMAL = 'Normal'
    TRUSTED_ONLY = 'Trusted'
    SUDO_ONLY = 'Sudo'

    @staticmethod
    def get_state(string):
        if string == State.NORMAL:
            return State.NORMAL
        if string == State.TRUSTED_ONLY:
            return State.TRUSTED_ONLY
        if string == State.SUDO_ONLY:
            return State.SUDO_ONLY
        return None

class Guard:
    AUTHOR = None
    AUTHOR_DM = None

    SUDO_IDS = set()
    SUDO_CHANNELS = set()

    TRUSTED_ROLES = set(['Verification Tier Level 2'])
    TRUSTED_USERS = set()

    BANNED_USERS = set()

    def __init__(self, state=State.NORMAL):
        """Initializes a guard to check user privilege"""
        self.state = state

    def allow(self, message):
        """Whether to allow the message given the current state of the guard"""
        if message.author.id == Guard.AUTHOR:
            return True
        if message.author.id in Guard.BANNED_USERS:
            return False
        if self.state == State.TRUSTED_ONLY and not Guard.is_trusted(message):
            return False
        if self.state == State.SUDO_ONLY and not Guard.allow_sudo(message):
            return False
        return True

    @staticmethod
    def allow_sudo(message):
        """Returns whether in the circumstances of the given message, a sudo action is allowed"""
        if message.author.id == Guard.AUTHOR and message.channel.type == discord.ChannelType.private:
            return True
        if message.author.id in Guard.SUDO_IDS and message.channel.id in Guard.SUDO_CHANNELS:
            return True
        return False

    @staticmethod
    def is_trusted(message):
        """Returns whether the circumstances of the message, the author is trusted"""
        author = message.author
        if author.id == Guard.AUTHOR:
            return True
        if author.id in Guard.BANNED_USERS:
            return False
        if author.id in Guard.TRUSTED_USERS:
            return True
        try:
            if set([role.name for role in author.roles]).intersection(Guard.TRUSTED_ROLES):
                return True
        except:
            return False
        return False

    @staticmethod
    def has_permission(message, permission):
        """Returns whether we have the specified permission when replying to the message"""
        if message.channel.type == discord.ChannelType.private:
            return True
        if getattr(message.channel.guild.me.permissions_in(message.channel), permission):
            return True
        return False

guard = Guard()

class Intent:
    DIRECT = 'Direct'
    MAP = 'Map'
    NONE = 'None'

    @staticmethod
    def get_intent(msg):
        """Returns the intent of the message, as defined by the Intent class
        """
        if re.search(MapController.MAP_REGEX, msg.content) and client.user.id in msg.raw_mentions:
            return Intent.MAP
        elif re.match(Controller.KEY_REGEX, msg.content):
            return Intent.DIRECT
        else:
            return Intent.NONE

def privileged(f):
    """Decorate a function as requiring sudo access
    """
    @wraps(f)
    def wrapper(self, msg, *args, **kwargs):
        if not Guard.allow_sudo(msg):
            return
        return f(self, msg, *args, **kwargs)
    return wrapper

RES_PATH = 'res'

class MapController:
    """The regex recognizing URL to the interactive Day R map"""
    MAP_REGEX = 'https://dayr-map.info/(?:index\.html)?\?(?:start\=true&)?clat\=([-0-9.]+)&clng\=([-0-9.]+)(?:&mlat\=([-0-9.]+)&mlng\=([-0-9.]+))?&zoom\=([-0-9.]+)'

    """The URL to the interactive map"""
    MAP_URL = 'https://dayr-map.info'

    """Stores the image of the world map"""
    map_image = None
    map_path = 'world_map_biomes_cities.png'

    """Stores the image of the marker"""
    marker_image = None
    marker_path = 'marker_event.png'

    """Mapping of all location names into their coordinates and size"""
    locations = {}

    """Controller for messages containing URL to the interactive Day R map
    """
    def __init__(self, clat, clng, zoom=0, mlat=None, mlng=None, start=False):
        self.clat = clat
        self.clng = clng
        self.zoom = zoom
        self.mlat = mlat
        self.mlng = mlng
        self.start = start

        self.has_marker = self.mlat is not None

    def __repr__(self):
        return f'clat: {self.clat}, clng: {self.clng}, mlat: {self.mlat}, mlng: {self.mlng}, zoom: {self.zoom}'

    __str__ = __repr__

    async def generate_snapshot(self, include_world=True):
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

    def is_valid(self, strict=False):
        if self.clat > 0 or self.clat < -9*512:
            return False
        if self.clng < 0 or self.clng > 16*512:
            return False
        if self.has_marker and (self.mlat > 0 or self.mlat < -9*512):
            return False
        if self.has_marker and (self.mlng < 0 or self.mlng > 16*512):
            return False
        if strict and (not (2*self.zoom).is_integer() or self.zoom < -3 or self.zoom > 5):
            return False
        return True

    def generate_url(self):
        """Generate the URL for this location"""
        if self.has_marker:
            marker_param = f'mlat={self.mlat}&mlng={self.mlng}&'
        else:
            marker_param = ''
        if self.start:
            start_param = 'start=true&'
        else:
            start_param = ''
        url = f'{MapController.MAP_URL}?{start_param}clat={self.clat}&clng={self.clng}&{marker_param}zoom={self.zoom}'
        return url

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

async def wait_until(dt):
    """Sleep until the specified datetime"""
    now = datetime.now()
    await sleep((dt - now).total_seconds())

async def schedule_status():
    """Schedule sending the status of the bot to author's DM"""
    while True:
        if controller.scheduled_status_date is not None:
            return
        controller.scheduled_status_date = datetime.now()+timedelta(hours=23)
        await wait_until(controller.scheduled_status_date)
        channel = await client.fetch_channel(Guard.AUTHOR_DM)
        await channel.send(**{
            'content': controller.get_status(),
            })
        controller.scheduled_status_date = None

async def schedule_activity():
    """Schedule setting the status of the bot"""
    if controller.scheduled_activity_date is not None:
        return
    controller.scheduled_activity_date = datetime.now()+timedelta(seconds=30)
    await wait_until(controller.scheduled_activity_date)
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for ~command'))

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    run(schedule_status())
    run(schedule_activity())

class Controller:
    # The list of supported commands, mapped to its description
    commands = {
            'help': ('', '❓ Show this help (and other bots\' help message too)', True, 0),
            'link': ('itemName', '🔗 Show the wikilink for the specified item', True, 10),
            'recipe': ('itemName', '📜 Show the recipe for the specified item', True, 10),
            'info': ('itemName', '🔍 Show the infobox for the specified item', True, 10),
            'trader': ('(itemName|placeName)', '🏛️ Show where we can buy the specified item or at the specified place', True, 10),
            'workshop': ('(itemName|placeName)', '🛠️ Show where we can craft the specified item or at the specified place', True, 10),
            'snapshot': ('("world") ("marker") lat lng (zoom)',
                ('📸 Show a snapshot of the map at the specified location and zoom (-3 to 5).\n'
                +'\tIf "world" is specified (without quotes) the world map is also shown\n'
                +'\tIf "marker" is specified (without quotes) a marker will be shown'), True, 60),
            'location': ('placeName', '📍 Show the location details of the specified place', True, 60),
            'distance': ('"place1" "place2"', '📐 Calculate the distance between the two places', True, 10),

            # Privileged commands below
            'echo': ('text', '🔤 Return back your text', False, 3),
            'set_key': ('regex (help_key)', '🗝️ Change the trigger key (and the text in help message)', False, 3),
            'set_activity': ('activity', '⚽ Set the bot\'s activity', False, 3),
            'clear_cache': ('', '🧹 Clear the cache', False, 3),
            'status': ('', 'ℹ️ Show the status of the bot', False, 3),
            'restate': ('[Normal|Trusted|Sudo]', '🔧 Change the state of the bot', False, 3),
            'manage': ('[add|remove] [BANNED_USERS|TRUSTED_USERS|TRUSTED_ROLES|SUDO_IDS|SUDO_CHANNELS] ENTITYID (ENTITYID)*',
                       '🔒 Manage the sudo list and trusted roles', False, 3),
            }

    # The regex to detect messages starting with a mention to this bot
    KEY_REGEX_TEMPLATE = f'^(<@[!&]?{CLIENT_ID}>|##TEMPLATE##).*$'
    KEY_REGEX= KEY_REGEX_TEMPLATE.replace('##TEMPLATE##', '~(?!~)')
    HELP_KEY = '~'

    prev_regex = None
    prev_help = None

    # The URL to wiki API
    WIKI_API_REV_URL = 'https://dayr.fandom.com/api.php?action=query&prop=revisions&rvprop=content&format=json&rvslots=main&titles='
    WIKI_API_SEARCH_URL = 'https://dayr.fandom.com/api.php?action=query&list=search&utf8=&format=json&srlimit=3&srprop=timestamp&srsearch='

    @staticmethod
    def get_args(msg):
        """Parse the message which has been determined to have DIRECT intent
        """
        match = re.match(Controller.KEY_REGEX, msg.content)
        full_command = msg.content[match.end(1):].strip()

        full_command = re.findall(r'(?:")[^"]+(?:")|[^" ]+', full_command)
        full_command = [token.strip('"') for token in full_command]
        if len(full_command) == 0:
            command = 'help'
            args = []
        elif len(full_command) == 1:
            command = full_command[0]
            args = []
        else:
            command = full_command[0]
            args = full_command[1:]
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
        self.start_time = datetime.utcnow()
        self.reply_count = 0
        self.reply_counts = Counter()
        self.trading_table = None
        self.workshop_table = None
        self.scheduled_status_date = None
        self.scheduled_activity_date = None
        self.author_dm = None

    def can_execute(self, msg, command, now):
        """Returns whether the author of the message is allowed to run the command
        """
        if command not in self.user_limit:
            return True, 0
        expiry = self.user_limit[command].get(msg.author.id, 0)
        return now > expiry, expiry-now

    @staticmethod
    async def http_get(url):
        """Asynchronous method to fetch a URL"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:
                return await r.text()

    @staticmethod
    @lru_cache(maxsize=WIKI_CACHE_LIMIT)
    async def get_wikitext(item):
        """Returns the wikitext of the specified item.

        This method handles redirects as well.
        """
        item = item.strip()
        url = Controller.WIKI_API_REV_URL + item
        response = await Controller.http_get(url)
        try:
            pages = json.loads(response)['query']['pages']
            key = list(pages.keys())[0]
            if key == '-1':
                raise ValueError('Page not found')
            wikitext = pages[key]['revisions'][0]['slots']['main']['*']
            while wikitext.startswith('#REDIRECT'):
                item = re.findall('([^[\]]+)(?:\]|$)', wikitext[len('#REDIRECT'):].strip())[0]
                url = Controller.WIKI_API_REV_URL + item
                response = await Controller.http_get(url) 
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

    async def execute(self, msg, command, args):
        """Entry point for any direct command
        """
        if not Guard.allow_sudo(msg) and not Controller.is_enabled(command):
            await self.not_found(msg, command)
            return
        now = time.time_ns()
        can_execute, delay = self.can_execute(msg, command, now)
        if can_execute:
            if command in self.user_limit:
                if Guard.is_trusted(msg):
                    delay = 5 * NS_IN_S
                else:
                    delay = self.user_limit[command]['delay'] * NS_IN_S
                self.user_limit[command][msg.author.id] = now + delay
            await self.__getattribute__(command)(msg, *args)
            self.reply_count += 1
            self.reply_counts[command] += 1
        else:
            if delay < 1:
                delay = f'{delay / NS_IN_S:.1f}'
            else:
                delay = f'{delay // NS_IN_S}'
            await msg.channel.send(**{
                'content': f'You can only use this command in {delay} more seconds',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })

    @staticmethod
    async def canonical_title(title):
        """Returns the canonical title for the given title, if found"""
        url = Controller.WIKI_API_SEARCH_URL + title
        response = await Controller.http_get(url)
        try:
            pages = json.loads(response)['query']['search']
            if len(pages) == 0:
                return None
            for page in pages:
                if page['title'].lower() == title.lower():
                    return page['title']
            return pages[0]['title']
        except:
            return None

    @staticmethod
    def link_from_title(title):
        page_url = f'<https://dayr.fandom.com/wiki/{aiohttp.helpers.quote(title)}>'
        return page_url

    async def link(self, msg, item=None, *args):
        """Replies the user with the wikilink for the specified item
        """
        if not Guard.has_permission(msg, 'embed_links'):
            await msg.channel.send(**{
                'content': 'Cannot send links on this channel',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        if not item:
            return
        if args:
            item = f'{item} {" ".join(args)}'
        title = await Controller.canonical_title(item)
        if title is None:
            await msg.channel.send(**{
                'content': f'There are no pages matching `{item}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        page_url = Controller.link_from_title(title)
        await msg.channel.send(**{
            'content': page_url,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def recipe(self, msg, item=None, *args):
        """Replies the user with the crafting recipe of the given item
        """
        if not Guard.has_permission(msg, 'embed_links'):
            await msg.channel.send(**{
                'content': 'I need embed_links permission to answer in this channel',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        if not item:
            return
        if args:
            item = f'{item} {" ".join(args)}'
        canonical = await Controller.canonical_title(item)
        if canonical:
            item = canonical
        page_url = Controller.link_from_title(item)
        if item == 'BelAZ':
            content = f'To complete the mission "Moving Town" to get BelAZ, you need:\n'
            content += '• Nuclear reactor part x3\n'
            content += '• Clean water x1,000\n'
            content += '• Auto spare parts x200\n'
            content += '• Screw x200\n'
            content += '• Machine oil x5,000\n'
            content += '• Car battery x50\n'
            content += '• Titanium alloy x100\n'
            content += '• Armor plate x100\n'
            content += '• High-performance capacitor x100\n'
            content += '• Lead x100,000\n'
            content += '• Insulating tape x1,000'
            await msg.channel.send(**{
                'content': content,
                'reference': msg.to_reference(),
                'mention_author': True,
                })
            return
        try:
            wikitext = await Controller.get_wikitext(item)
        except ValueError as e:
            # Means the page is not found
            await msg.channel.send(**{
                'content': f'No page found for `{item}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        try:
            emojis = {emoji.name.lower(): f'<:{emoji.name}:{emoji.id}> ' for emoji in msg.guild.emojis if emoji.available}
            for k, v in list(emojis.items()):
                emojis[k+'s'] = v
        except:
            emojis = {}
        parsed = WTP.parse(wikitext)
        content = None
        template_names = []
        for template in parsed.templates:
            template_names.append(template.name.strip())
            if template.name.strip().lower() == 'recipe':
                args = template.arguments
                logging.info(args)
                ingredients = []
                tools = []
                level = []
                points = []
                def parse_args(args):
                    idx = 0
                    while idx < len(args):
                        arg = args[idx].string.strip(' |')
                        if arg == '':
                            idx += 1
                            continue
                        if '=' not in arg:
                            amount = args[idx+1].string.strip(' |')
                            if not amount or amount != '0':
                                ingredients.append(f'{emojis.get(arg.lower().replace(" ", "_"), "")}{arg.capitalize()} x{amount}')
                            else:
                                ingredients.append(f'{emojis.get(arg.lower().replace(" ", "_"), "")}{arg.capitalize()}')
                            idx += 1
                        elif arg.startswith('Tool'):
                            tools.append(arg.split('=', maxsplit=1)[1].strip().capitalize())
                        elif arg.startswith('input'):
                            templates = WTP.parse(arg.split('=', maxsplit=1)[1].strip()).templates
                            if len(templates) > 0:
                                parse_args(templates[0].arguments)
                        elif arg.startswith('level'):
                            try:
                                level.append(int(arg.split('=')[1].strip()))
                            except:
                                pass
                        elif arg.startswith('research'):
                            try:
                                points.append(int(arg.split('=')[1].strip()))
                            except:
                                pass
                        idx += 1
                parse_args(args)
                requirements = ''
                if level:
                    if points:
                        requirements = f' (level {level[0]}, {points[0]} points)'
                    else:
                        requirements = f' (level {level[0]})'
                ingredients = '• '+'\n• '.join(ingredients)
                tools = '• '+'\n• '.join(tools) if tools else ''
                content = f'To craft {item}{requirements}, you need:\n{ingredients}'
                if tools:
                    content = f'{content}\nAnd these tools:\n{tools}'
                break
        logging.info(f'Templates in {item}: {", ".join(template_names)}')
        for table in parsed.tables:
            if 'Ingredients' in table:
                rows = table.string.split('|-')[1:]
                ingredients = [row.strip(' \t\n|').split('\n')[0].strip(' \t\n|').replace('[[', '').replace(']]', '').split('|')[-1] for row in rows]
                ingredients = [f'{emojis.get(" ".join(ingredient.split(" ")[:-1]).lower().replace(" ", "_"), "")}{ingredient}' for ingredient in ingredients]
                ingredients = '• '+'\n• '.join(ingredients)
                content = f'To cook {item}, you need:\n{ingredients}'
                break
        if content is None:
            await msg.channel.send(**{
                'content': f'No recipe found for `{item}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        content += f'\nSource: {page_url}'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    def is_infobox(self, name):
        """Returns True if the template name is a type of infobox
        """
        name = name.strip()
        if name.lower().startswith('infobox'):
            return True
        if name == 'Armors_(NEW)':
            return True
        if name == 'All_inclusive_infobox_2020':
            return True
        if name.lower() == 'item':
            return True
        return False

    async def info(self, msg, item=None, *args):
        """Replies the user with the information from infobox of the specified item
        """
        if not Guard.has_permission(msg, 'embed_links'):
            await msg.channel.send(**{
                'content': 'I need embed_links permission to answer in this channel',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        if not item:
            return
        if args:
            item = f'{item} {" ".join(args)}'
        canonical = await Controller.canonical_title(item)
        if canonical:
            item = canonical
        page_url = Controller.link_from_title(item)
        try:
            wikitext = await Controller.get_wikitext(item)
        except ValueError as e:
            # Means the page is not found
            await msg.channel.send(**{
                'content': f'No page found for `{item}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        contents = []
        template_names = []
        for template in WTP.parse(wikitext).templates:
            template_names.append(template.name.strip())
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
                content = f'## **{title}** ##\nSource: {page_url}\n{template.name.strip()}\n{entries}'
                contents.append(content)
        logging.info(f'Templates at {item}: '+', '.join(template_names))
        if not contents:
            await msg.channel.send(**{
                'content': f'No infobox found for `{item}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        await msg.channel.send(**{
            'content': '\n===\n'.join(contents),
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def get_trading_table(self):
        """Fetch and cache the trading table from wiki
        """
        if self.trading_table is None:
            self.trading_table = {}
            wikitext = await Controller.get_wikitext('Trading')
            wikilines = wikitext.split('\n')
            start_line = 0
            for idx, line in enumerate(wikilines):
                if 'Full Trading Table' in line:
                    start_line = idx
                    break
            wikitext = '\n'.join(wikilines[idx+1:])
            for row in wikitext.split('|-')[1:-1]:
                try:
                    icon, base_name, item, price, _, currency, stock, min_level = row.split('||')
                    base_name = base_name.lower()
                    if base_name not in self.trading_table:
                        self.trading_table[base_name] = {}
                    trade_list = self.trading_table[base_name]
                    item_name = item.split(']]', 1)[1].strip(' []')
                    if item_name in ['Gunpowder', 'Sulfur', 'Saltpeter', 'Scrap', 'Lead', 'Machine oil']:
                        units = 100
                    elif item_name in ['Gasoline', 'Diesel']:
                        units = 1000
                    else:
                        units = 1
                    trade_list[item_name.lower()] = (item_name, int(price), currency, int(stock), units, int(min_level))
                except:
                    print(row)
                    raise
        return self.trading_table

    async def get_workshop_table(self):
        """Fetch and cache the workshop (specialist) table from wiki
        """
        if self.workshop_table is None:
            self.workshop_table = {}
            wikitext = await Controller.get_wikitext('Specialist')
            bases = re.split(r'(?:\|rowspan=[57]\||style="text-align:left" \|)', wikitext)[1:]
            idx = 0
            while idx < len(bases):
                base_name = bases[idx].split('<br>', 1)[1].split('||')[0]
                craftable = []
                self.workshop_table[base_name.lower()] = (base_name, craftable)
                idx += 1
                level = 1
                while idx < len(bases):
                    if bases[idx][bases[idx].find(']]')+2] == ' ':
                        # Craftable list
                        for item in bases[idx].split('|-', 1)[0].split('<br>'):
                            craftable.append((item.split(']] ')[1].strip('[]\n'), level))
                    else:
                        # Base name
                        break
                    idx += 1
                    level += 1
        return self.workshop_table

    async def trader(self, msg, arg=None, *args):
        """Replies the user with a list of places that trade for and from the item
        if the argument is an item name, and a list of possible trades if the argument is a location name

        If the argument is empty, replies the user with the list of possible trading locations
        """
        trading_table = await self.get_trading_table()
        self_delete = False

        if not arg:
            content = '• '+'\n• '.join(place.capitalize() for place in trading_table.keys())
            content = f'Places you can trade:\n{content}'
        else:
            if args:
                arg = f'{arg} {" ".join(args)}'
            # Check for place name
            content = ''
            if arg.lower() in trading_table:
                # A location name
                trade_list = []
                for item_name, price, currency, stock, units, min_level in trading_table[arg.lower()].values():
                    trade_list.append(f'• **{units} {item_name}** for __{price} {currency}__ (max {stock}), level {min_level}')
                content += f'Trading in {arg.capitalize()}:\n'+'\n'.join(trade_list)
            if not content:
                # An item name or not found
                item = arg
                trade_list = []
                for base_name, items in trading_table.items():
                    aliases = [item.lower(), item+'s'.lower(), item[:-1].lower() if item[-1] == 's' else '', item+' metal', 'sulfuric '+item]
                    for alias in aliases:
                        if not alias:
                            continue
                        if alias in items:
                            item_name, price, currency, stock, units, min_level = items[alias]
                            trade_list.append(f'• At **{base_name.capitalize()}**: {units} {item_name} for {price} {currency} (max {stock}), level {min_level}')
                if len(trade_list) == 0:
                    content = f'Could not find any trading option for `{item}`'
                    self_delete = True
                else:
                    content = f'Places that sells {item}:\n'
                    content += '\n'.join(trade_list)
        response = {
                'content': content,
                'reference': msg.to_reference(),
                'mention_author': True,
                }
        if self_delete:
            response['delete_after'] = 3
        await msg.channel.send(**response)

    async def workshop(self, msg, arg=None, *args):
        """Replies the user with a list of places that sells the specified item
        if the argument is an item name, and a list of possible trades if the argument is a location name

        If the argument is empty, replies the user with the list of possible trading locations
        """
        workshop_table = await self.get_workshop_table()
        self_delete = False

        if not arg:
            content = '• '+'\n• '.join(place.capitalize() for place in workshop_table.keys())
            content = f'Places with workshop:\n{content}'
        else:
            if args:
                arg = f'{arg} {" ".join(args)}'
            # Check for place name
            content = ''
            if arg.lower() in workshop_table:
                # A location name
                base_name, craftables = workshop_table[arg.lower()]
                craft_list = []
                for item_name, level in craftables:
                    craft_list.append(f'• {item_name} (workshop level {level})')
                content += f'Craftable in {arg.capitalize()}:\n'+'\n'.join(craft_list)
            if not content:
                # An item name or not found
                item = arg
                craft_list = []
                for base_name, craftables in workshop_table.values():
                    aliases = [item.lower(), item+'s'.lower(), item[:-1].lower() if item[-1] == 's' else '', item+' metal', 'sulfuric '+item]
                    for alias in aliases:
                        if not alias:
                            continue
                        for craftable, level in craftables:
                            if alias == craftable.lower():
                                craft_list.append(f'• {base_name.capitalize()} (at workshop level {level})')
                if len(craft_list) == 0:
                    content = f'Could not find any workshop crafting option for `{item}`'
                    self_delete = True
                else:
                    content = f'Places that can craft {item}:\n'
                    content += '\n'.join(craft_list)
        response = {
                'content': content,
                'reference': msg.to_reference(),
                'mention_author': True,
                }
        if self_delete:
            response['delete_after'] = 3
        await msg.channel.send(**response)

    async def snapshot(self, msg, *args):
        """Replies the user with a snapshot of the specified location
        """
        if not Guard.has_permission(msg, 'attach_files'):
            await msg.channel.send(**{
                'content': 'Cannot send images on this channel',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        if not args:
            return
        args = list(args)
        if args[0] == 'world':
            include_world = True
            args.pop(0)
        else:
            include_world = False
        if args and args[0] == 'marker':
            show_marker = True
            args.pop(0)
        else:
            show_marker = False
        try:
            if len(args) == 2:
                lat, lng = map(float, args)
                zoom = 0
            elif len(args) == 3:
                lat, lng, zoom = map(float, args)
            else:
                return
        except:
            return
        if show_marker:
            map_controller = MapController(lat, lng, zoom, mlat=lat, mlng=lng)
        else:
            map_controller = MapController(lat, lng, zoom)
        if not map_controller.is_valid():
            await msg.channel.send(**{
                'content': f'Invalid location {lat} {lng} {zoom}',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        image = await map_controller.generate_snapshot(include_world=include_world)
        snapshot_id = map_controller.get_id().replace('_', ', ').replace('m', '')
        location_str = f'center at -{snapshot_id}'
        content = f'Here is a snapshot of that location ({location_str}).'
        await msg.channel.send(**{
            'content': content,
            'file': discord.File(image, filename=f'snapshot_{map_controller.get_id()}.png'),
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def location(self, msg, place_name=None, *args):
        """Replies the user with the coordinates of the given place, as well as the snapshot and the URL
        """
        if not place_name:
            return
        if args:
            place_name = f'{place_name} {" ".join(args)}'
        if place_name.lower() in MapController.locations:
            lat, lng, size = MapController.locations[place_name.lower()]
            map_controller = MapController(lat, lng, 1, lat, lng)

            content = f'The location `{place_name}` is located at ({lat:.2f}, {lng:.2f})'
            if Guard.has_permission(msg, 'embed_links'):
                # If can embed link, post the URL too
                url = map_controller.generate_url()
                content = f'{content}\nURL: <{url}>'

            response = {
                'content': content,
                'reference': msg.to_reference(),
                'mention_author': True,
                }

            if Guard.has_permission(msg, 'attach_files'):
                # If can post image, post the snapshot too
                image = await map_controller.generate_snapshot(include_world=True)
                response['file'] = discord.File(image, filename=f'snapshot_{map_controller.get_id()}.png')
            await msg.channel.send(**response)
        else:
            await msg.channel.send(**{
                'content': f'There is no location named `{place_name}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })

    async def distance(self, msg, place1=None, place2=None, *args):
        """Replies the user with the distance between the two place names mentioned
        """
        if not place1 or not place2:
            return
        try:
            if place1.lower() not in MapController.locations:
                raise ValueError(place1)
            if place2.lower() not in MapController.locations:
                raise ValueError(place2)
        except ValueError as e:
            await msg.channel.send(**{
                'content': f'There is no location named `{e.args[0]}`',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
        lat1, lng1, _ = MapController.locations[place1.lower()]
        lat2, lng2, _ = MapController.locations[place2.lower()]
        distance = ((lat1-lat2)**2 + (lng1-lng2)**2)**0.5
        content = f'The distance between {place1} ({lat1}, {lng1}) and {place2} ({lat2}, {lng2}) is {distance:.0f}km.'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    async def help(self, msg, *args, intro=None):
        """Replies the user with the help message
        """
        sudo = Guard.allow_sudo(msg)
        if intro is not None:
            intro = f'{intro.strip()} '
        else:
            intro = ''
        if msg.channel.type == discord.ChannelType.private:
            nick = '@DayRInfo'
        else:
            nick = f'@{msg.channel.guild.me.nick}'
        print_general_help = True
        if len(args) > 0:
            command = args[0]
            arg, desc, enabled, delay = Controller.commands.get(command, (None, None, None, None))
            if desc and (sudo or enabled):
                print_general_help = False
                content = f'`{Controller.HELP_KEY}{command}{arg}`{desc}'
            await msg.channel.send(**{
                'content': content,
                'reference': msg.to_reference(),
                'mention_author': True,
                })
        if print_general_help:
            content = f'{intro}I understand the following commands (tag me at the start of the message):\n'
            for command, (arg, desc, enabled, delay) in Controller.commands.items():
                if not sudo and not enabled:
                    continue
                if arg:
                    arg = f' {arg.strip()}'
                if desc:
                    desc = f'\n\t{desc}'
                content = f'{content}`{Controller.HELP_KEY}{command}{arg}`{desc}\n'
            content = f'{content}----------\n'
            content = f'{content}• Also, if you tag this bot ({nick}) on a message containing a link to the interactive Day R map 🗺️ with a location URL, I will send you a snapshot of the location.\n'
            content = f'{content}• React with ❌ to any of my messages to delete it (if I still remember that it was my message). You can only delete my messages that are directed to you.'
            await msg.author.send(**{
                'content': content,
                })
            await msg.channel.send(**{
                'content': 'Command list sent via DM!',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })

    async def not_found(self, msg, command):
        """Replies the user with the help message, prepended with the information about invalid command
        """
        await msg.channel.send(**{
            'content': f'I do not understand `{command}`',
            'reference': msg.to_reference(),
            'mention_author': True,
            'delete_after': 3,
            })

    ###################################
    ### Below are private functions ###
    ###################################

    @privileged
    async def echo(self, msg, text=None, *args):
        """Replies the user with their own message
        """
        if text is None:
            text = ''
        if args:
            text = '{text} {" ".join(args)}'
        await msg.channel.send(**{
            'content': text,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    @privileged
    async def set_key(self, msg, regex=None, help_key=None, *args):
        """Sets the additional trigger phrase for the bot
        """
        if regex is None:
            return
        Controller.prev_regex = Controller.KEY_REGEX
        Controller.prev_help = Controller.HELP_KEY
        Controller.KEY_REGEX = Controller.KEY_REGEX_TEMPLATE.replace('##TEMPLATE##', regex)
        if help_key is None:
            help_key = regex
        Controller.HELP_KEY = help_key
        content = f'Additional trigger phrase updated to `{regex}`, and help key to `{help_key}`.\n'
        content = f'{content}Send me the `confirm` command within 5s to confirm the change.'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })
        await sleep(5)
        if Controller.prev_regex is None:
            return
        Controller.KEY_REGEX = Controller.prev_regex
        Controller.HELP_KEY = Controller.prev_help
        await msg.channel.send(**{
            'content': 'No command received within the confirmation duration, reverting',
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    @privileged
    async def confirm(self, msg, *args):
        """Confirms the set_key command"""
        if Controller.prev_regex is None:
            await msg.channel.send(**{
                'content': 'No key change in progress',
                'reference': msg.to_reference(),
                'mention_author': True,
                })
            return
        Controller.prev_regex = None
        Controller.prev_help = None
        await msg.channel.send(**{
            'content': 'Key change confirmed',
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    @privileged
    async def set_activity(self, msg, activity=None, *args):
        """Sets the activity of the bot"""
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=activity))

    @privileged
    async def clear_cache(self, msg, *args):
        """Clears the cache
        """
        Controller.get_wikitext.cache_clear()
        self.trading_table = None
        await msg.channel.send(**{
            'content': 'Cache cleared',
            })

    def get_status(self):
        content = f'Start time: {self.start_time}\n'
        content = f'{content}KEY_REGEX: {Controller.KEY_REGEX}\n'
        content = f'{content}HELP_KEY: {Controller.HELP_KEY}\n'
        content = f'{content}State: {guard.state}\n'
        content = f'{content}SUDO_IDS: {Guard.SUDO_IDS}\n'
        content = f'{content}SUDO_CHANNELS: {Guard.SUDO_CHANNELS}\n'
        content = f'{content}TRUSTED_ROLES: {Guard.TRUSTED_ROLES}\n'
        content = f'{content}BANNED_USERS: {Guard.BANNED_USERS}\n'
        content = f'{content}Reply count: {self.reply_count}\n'
        content = f'{content}Reply count per command:'
        for command, count in self.reply_counts.items():
            content += f'\n• {command}: {count}'
        return content

    @privileged
    async def status(self, msg, *args):
        """Send some status about the bots
        """
        content = self.get_status()
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    @privileged
    async def restate(self, msg, state_str=None, *args):
        """Changes the state of the bot
        """
        state = State.get_state(state_str)
        if state is None:
            content = f'Unknown state: `{state_str}`'
        elif guard.state == state:
            content = f'Already in {state}'
        else:
            guard.state = state
            if state == State.NORMAL:
                content = 'Resuming operations from all users'
            elif state == State.TRUSTED_ONLY:
                content = 'Only trusted users will be replied'
            elif state == State.SUDO_ONLY:
                content = 'Only allowing sudo access'
            else:
                content = 'Unhandled state: `{state}`'
        await msg.channel.send(**{
            'content': content,
            'reference': msg.to_reference(),
            'mention_author': True,
            })

    @privileged
    async def manage(self, msg, *args):
        """Manages the guard of this bot

        Syntax: manage [add | remove] [BANNED_USERS | TRUSTED_USERS | TRUSTED_ROLES | SUDO_IDS | SUDO_CHANNELS] ENTITYID (ENTITYID)*
        """
        if len(args) < 3:
            return
        sub_command = args[0]
        if sub_command not in ['add', 'remove']:
            return
        var = args[1]
        if var not in ['BANNED_USERS', 'TRUSTED_USERS', 'TRUSTED_ROLES', 'SUDO_IDS', 'SUDO_CHANNELS']:
            return
        if var == 'BANNED_USERS':
            var = Guard.BANNED_USERS
        elif var == 'TRUSTED_USERS':
            var = Guard.TRUSTED_USERS
        elif var == 'TRUSTED_ROLES':
            var = Guard.TRUSTED_ROLES
        elif var == 'SUDO_IDS':
            var = Guard.SUDO_IDS
        elif var == 'SUDO_CHANNELS':
            var = Guard.SUDO_CHANNELS
        else:
            return
        entityids = args[2:]
        for entityid in entityids:
            if sub_command == 'add':
                var.add(int(entityid))
            elif sub_command == 'remove':
                var.remove(int(entityid))
        await msg.add_reaction('🆗')
        if self.author_dm is None:
            self.author_dm = await client.fetch_channel(Guard.AUTHOR_DM)
        await self.author_dm.send(**{
            'content': f'{msg.author} ({msg.author.id}): {args}',
            })

controller = Controller()

@client.event
async def on_reaction_add(reaction, user):
    try:
        if reaction.message.author == client.user and (reaction.message.channel.type == discord.ChannelType.private or reaction.message.reference.cached_message.author == user) and reaction.emoji == '❌':
            await reaction.message.delete()
    except Exception as e:
        logging.error(e)
        return

@client.event
async def on_message(message):
    if message.author == client.user:
        # If this is our own (the bot's) message, ignore it
        return

    # Privilege check
    if not guard.allow(message):
        return

    logging.info((f'Received message: {message.content}\n'
                 +f'.\tFrom {message.author} ({message.author.id})\n'
                 +f'.\tIn {message.channel} ({message.channel.id})\n'
                 +f'.\tServer {message.guild} ({message.guild.id if message.guild else ""})\n'
                 +f'.\tAt {message.created_at}'))
    intent = Intent.get_intent(message)
    logging.info(f'Intent: {intent}')
    if intent == Intent.DIRECT:
        command, args = controller.get_args(message)
        logging.info(f'Command: {command}, args: {args}')
        await controller.execute(message, command, args)
    elif intent == Intent.MAP:
        if not Guard.has_permission(message, 'attach_files'):
            await msg.channel.send(**{
                'content': 'Cannot send images on this channel',
                'reference': msg.to_reference(),
                'mention_author': True,
                'delete_after': 3,
                })
            return
            
        matches = re.finditer(MapController.MAP_REGEX, message.content)
        for idx, match in enumerate(matches):
            map_controller = MapController.from_match(match)
            logging.info(f'Generating image for {map_controller}')
            image = await map_controller.generate_snapshot()
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
        run(message.add_reaction('🗺️')) # map emoji

def main(args=None):
    parser = ArgumentParser(description='')
    parser.add_argument('--token_path', default='token.txt',
                        help='The path to the token')
    parser.add_argument('--location_path', default='location_marker.json',
                        help='The path to list of locations')
    args = parser.parse_args(args)
    token_path = args.token_path
    location_path = args.location_path
    try:
        with open(token_path, 'r') as infile:
            TOKEN = infile.read().strip()
    except:
        TOKEN = os.environ.get('TOKEN')
    try:
        with open('author.txt', 'r') as infile:
            Guard.AUTHOR = int(infile.read().strip())
        with open('author_dm.txt', 'r') as infile:
            Guard.AUTHOR_DM= int(infile.read().strip())
    except:
        Guard.AUTHOR = int(os.environ.get('AUTHOR'))
        Guard.AUTHOR_DM = int(os.environ.get('AUTHOR_DM'))
    Guard.SUDO_IDS.add(Guard.AUTHOR)
    try:
        # Map all location names (in all languages) into their lat, lng and size (for name collision handling)
        with open(location_path, 'r') as infile:
            location_data = json.load(infile)
        for location in location_data:
            lng, lat = location['geometry']['coordinates']
            size = location['properties']['size']
            for name in location['properties']['name'].values():
                name = name.lower()
                if '<br>' in name:
                    name = name.split('<br>/ ')[-1]
                if name not in MapController.locations or size > MapController.locations[name][2]:
                    MapController.locations[name] = (lat, lng, size)
    except:
        logging.info(f'Cannot read location marker data from {location_path}')
    client.run(TOKEN)

if __name__ == '__main__':
    main()

