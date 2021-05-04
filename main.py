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

CLIENT_ID = '839181905249304606'
CLIENT_SECRET = None

PUBLIC_KEY = '8e3a6e541e5954298dc0087903037ef6d7c5480d599f2ae8c25d796af4e6ac25'

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('$hello'):
        await message.channel.send('Hello!')

def main(args=None):
    parser = ArgumentParser(description='')
    parser.add_argument('--client_secret_path', default='client_secret.txt',
                        help='The path to client secret')
    args = parser.parse_args(args)
    client_secret_path = args.client_secret_path
    with open(client_secret_path, 'r') as infile:
        CLIENT_SECRET = infile.read().strip()

    client = discord.Client()
    client.run(CLIENT_SECRET)

if __name__ == '__main__':
    main()

