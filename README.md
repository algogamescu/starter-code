# AlgoPoker Starter Code

AlgoPoker starter code for developing bots to play Heads-Up No-Limit Hold'em against eachother.

## Getting Started

Before getting started, you are going to need to have [Python 3](https://www.python.org/downloads/) installed

To get started, first you should download this code. You can do that by clicking `Code` then `Download ZIP`.

With that done, once you have the code locally you can install the dependencies with

```sh
pip3 install -r requirements.txt
```

You can then begin developing your bot by editing the `player.py` file in the `starter_bot` folder.

Currently in `starter_bot` is a bot that always raises by the minimum amount.

## Testing Your Bot

When you want to test your bot, you can play against it in the playground. To run this, you will need to run

```sh
python3 playground.py
```

Then in a different terminal window run

```sh
python3 -m http.server 8000 --directory playground_bot/statc
```

You should then be able to go to [http://localhost:8000](http://localhost:8000) and play against your bot.
