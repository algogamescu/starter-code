from skeleton.actions import FoldAction, CallAction, CheckAction, RaiseAction
from skeleton.states import GameState, TerminalState, RoundState
from skeleton.states import NUM_ROUNDS, STARTING_STACK, BIG_BLIND, SMALL_BLIND
from skeleton.bot import Bot
from skeleton.runner import parse_args, run_bot

import socketio
import time

class Player(Bot):    
    def __init__(self):
        '''
        Called when a new game starts. Called exactly once.

        Arguments:
        Nothing.

        Returns:
        Nothing.
        '''

        self.sio = socketio.Client()

        @self.sio.event
        def connect():
            self.sio.emit('player_connected')

        self.sio.connect('http://127.0.0.1:2000/')

    def handle_new_round(self, game_state, round_state, active):
        '''
        Called when a new round starts. Called NUM_ROUNDS times.

        Arguments:
        game_state: the GameState object.
        round_state: the RoundState object.
        active: your player's index.

        Returns:
        Nothing.
        '''

        my_bankroll = game_state.bankroll  # the total number of chips you've gained or lost from the beginning of the game to the start of this round
        game_clock = game_state.game_clock  # the total number of seconds your bot has left to play this game
        round_num = game_state.round_num  # the round number from 1 to NUM_ROUNDS
        my_cards = round_state.hands[active]  # your cards
        big_blind = bool(active)  # True if you are the big blind

        self.sio.emit('player_new_round_state', { 
            'my_bankroll': my_bankroll, 
            'round_num': round_num, 
            'my_cards': my_cards 
        })

    def handle_round_over(self, game_state, terminal_state, active):
        '''
        Called when a round ends. Called NUM_ROUNDS times.

        Arguments:
        game_state: the GameState object.
        terminal_state: the TerminalState object.
        active: your player's index.

        Returns:
        Nothing.
        '''

        my_delta = terminal_state.deltas[active]  # your bankroll change from this round
        previous_state = terminal_state.previous_state  # RoundState before payoffs
        street = previous_state.street  # 0, 3, 4, or 5 representing when this round ended
        my_cards = previous_state.hands[active]  # your cards
        opp_cards = previous_state.hands[1-active]  # opponent's cards or [] if not revealed

        self.finished_showing = False
        self.sio.emit('player_end_round_state', { 'opp_cards': opp_cards, 'my_delta': my_delta })

        if len(opp_cards) > 0: # wait longer if we are at showdown
            time.sleep(7)
        else:
            time.sleep(1)

    def get_action(self, game_state, round_state, active):
        '''
        Where the magic happens - your code should implement this function.
        Called any time the engine needs an action from your bot.

        Arguments:
        game_state: the GameState object.
        round_state: the RoundState object.
        active: your player's index. 

        Returns:
        Your action.
        '''
        legal_action_to_text = {
            CheckAction: 'check',
            FoldAction: 'fold',
            CallAction: 'call',
            RaiseAction: 'raise'
        }
        legal_actions = round_state.legal_actions()  # the actions you are allowed to take
        legal_actions_list = [legal_action_to_text[action] for action in legal_actions]
        street = round_state.street  # 0, 3, 4, or 5 representing pre-flop, flop, turn, or river respectively
        my_cards = round_state.hands[active]  # your cards
        board_cards = round_state.deck[:street]  # the board cards
        my_pip = round_state.pips[active]  # the number of chips you have contributed to the pot this round of betting
        opp_pip = round_state.pips[1-active]  # the number of chips your opponent has contributed to the pot this round of betting
        my_stack = round_state.stacks[active]  # the number of chips you have remaining
        opp_stack = round_state.stacks[1-active]  # the number of chips your opponent has remaining
        continue_cost = opp_pip - my_pip  # the number of chips needed to stay in the pot
        my_contribution = STARTING_STACK - my_stack  # the number of chips you have contributed to the pot
        opp_contribution = STARTING_STACK - opp_stack  # the number of chips your opponent has contributed to the pot
        pot_size = my_contribution + opp_contribution - my_pip - opp_pip
        min_raise, max_raise = round_state.raise_bounds()  # the smallest and largest numbers of chips for a legal bet/raise
        
        self.actualAction = None

        def actionLooper():
            while self.actualAction == None:
                time.sleep(0.3)
            return self.actualAction

        @self.sio.on('player_act_check')
        def player_act_check():
            if CheckAction in legal_actions:
                self.actualAction = CheckAction()

        @self.sio.on('player_act_fold')
        def player_act_fold():
            if FoldAction in legal_actions:
                self.actualAction = FoldAction()

        @self.sio.on('player_act_call')
        def player_act_call():
            if CallAction in legal_actions:
                self.actualAction = CallAction()

        @self.sio.on('player_act_raise')
        def player_act_raise(data):
            if RaiseAction in legal_actions:
                self.actualAction = RaiseAction(data['amount'])

        self.sio.emit('player_update_round_state', {
            'board_cards': board_cards,
            'my_cards':my_cards,
            'my_stack': my_stack,
            'opp_stack': opp_stack,
            'my_stack': my_stack,
            'my_pip': my_pip,
            'opp_pip':opp_pip,
            'min_raise':min_raise,
            'max_raise':max_raise, 
            'pot_size':pot_size,
            'legal_actions_list':legal_actions_list
        })
        
        return actionLooper()


if __name__ == '__main__':
    run_bot(Player(), parse_args())
