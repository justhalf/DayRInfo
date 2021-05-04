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

logging.basicConfig(level=logging.INFO)

CLIENT_ID = '839181905249304606'

PUBLIC_KEY = '8e3a6e541e5954298dc0087903037ef6d7c5480d599f2ae8c25d796af4e6ac25'

TOKEN = None

client = discord.Client()

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('$hello'):
        logging.info(f'{dir(message)}')
        logging.info(f'Received message: {message.content} from {message.author} at {message.created_at}')
        await message.add_reaction('\U0001f44c')
        await message.channel.send(**{
            'content': 'Hello too!',
            'reference': message.to_reference(),
            'mention_author': True,
            'embed': discord.Embed.from_dict({
                'title': 'An image',
                'image': {
                    'url': 'https://dayr-map.info/map_tiles/0/7/4.png',
                    }
                }),
            })

def main(args=None):
    global client
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

