from numpy.random import geometric
from collections import namedtuple
from threading import Thread
from queue import Queue
import time
import json
import subprocess
import socket
import eval7
import sys
import os

sys.path.append(os.getcwd())
from config import *

FoldAction = namedtuple('FoldAction', [])
CallAction = namedtuple('CallAction', [])
CheckAction = namedtuple('CheckAction', [])
# we coalesce BetAction and RaiseAction for convenience
RaiseAction = namedtuple('RaiseAction', ['amount'])
TerminalState = namedtuple('TerminalState', ['deltas', 'previous_state'])

STREET_NAMES = ['Flop', 'Turn', 'River']
DECODE = {'F': FoldAction, 'C': CallAction, 'K': CheckAction, 'R': RaiseAction}
CCARDS = lambda cards: ','.join(map(str, cards)) #community cards
PCARDS = lambda cards: '{}'.format(' '.join(map(str, cards)))
PVALUE = lambda name, value: ', {} ({})'.format(name, value)
STATUS = lambda players: ''.join([PVALUE(p.name, p.bankroll) for p in players])


class RoundState(namedtuple('_RoundState', ['button', 'street', 'pips', 'stacks', 'hands', 'deck', 'previous_state'])):
    #note that the button is incremented with each move. Set to 0 for preflop. Resets to 1 at each street.
    '''
    Encodes the game tree for one round of poker.
    '''

    def showdown(self):
        '''
        Compares the players' hands and computes payoffs.
        '''
        score0 = eval7.evaluate(self.deck.peek(5) + self.hands[0]) #index 0 score
        score1 = eval7.evaluate(self.deck.peek(5) + self.hands[1]) #index 1 score
        if score0 > score1:
            delta = STARTING_STACK - self.stacks[1] #index 0 won, so they get whatever index 1 bet
        elif score0 < score1:
            delta = self.stacks[0] - STARTING_STACK #index 1 won, so they get whatever index 0 bet
        else:  # split the pot
            delta = (self.stacks[0] - self.stacks[1]) // 2
        return TerminalState([delta, -delta], self) #returns the roundstate where the player stacks are changed by the correct amount

    def legal_actions(self):
        '''
        Returns a set which corresponds to the active player's legal moves.
        '''
        active = self.button % 2 #set active player
        continue_cost = self.pips[1-active] - self.pips[active] #continue cost is the difference in pips
        if continue_cost == 0:
            # we can only raise the stakes if both players can afford it
            bets_forbidden = (self.stacks[0] == 0 or self.stacks[1] == 0)
            return {CheckAction} if bets_forbidden else {CheckAction, RaiseAction} #can't unnecessarily fold if they just check
        # continue_cost > 0
        # similarly, re-raising is only allowed if both players can afford it
        raises_forbidden = (continue_cost == self.stacks[active] or self.stacks[1-active] == 0)
        return {FoldAction, CallAction} if raises_forbidden else {FoldAction, CallAction, RaiseAction} #fold/call if cant raise. fold/call/raise if can raise
        

    def raise_bounds(self):
        '''
        Returns a tuple of the minimum and maximum legal raises.
        '''
        active = self.button % 2 #set active player
        continue_cost = self.pips[1-active] - self.pips[active] #continue cost is the difference in pips
        max_contribution = min(self.stacks[active], self.stacks[1-active] + continue_cost) #my contribution right now is up to min(my stack, opponent stack + difference in pips)
        min_contribution = min(max_contribution, continue_cost + max(continue_cost, BIG_BLIND)) #my contribution right now is at least max(2*continue cost, continue cost + bb) but if this is more than the max, then i can go all in
        return (self.pips[active] + min_contribution, self.pips[active] + max_contribution) #return tuple with the bounds for pips
    def proceed_street(self):
        '''
        Resets the players' pips and advances the game tree to the next round of betting.
        '''
        if self.street == 5: #if proceed at river, go to showdown
            return self.showdown()
        new_street = 3 if self.street == 0 else self.street + 1 #set street appropriately to flop, turn, river
        return RoundState(1, new_street, [0, 0], self.stacks, self.hands, self.deck, self) #reset pips and button to 1
    def proceed(self, action):
        '''
        Advances the game tree by one action performed by the active player.
        '''
        active = self.button % 2 #active player index
        if isinstance(action, FoldAction):
            delta = self.stacks[0] - STARTING_STACK if active == 0 else STARTING_STACK - self.stacks[1] #active player folded. Set delta accordingly
            return TerminalState([delta, -delta], self)
        if isinstance(action, CallAction):
            if self.button == 0:  # sb called bb
                return RoundState(1, 0, [BIG_BLIND] * 2, [STARTING_STACK - BIG_BLIND] * 2, self.hands, self.deck, self) #bb moves first next
            # both players acted
            new_pips = list(self.pips) #initialise new pips and new stacks
            new_stacks = list(self.stacks)
            contribution = new_pips[1-active] - new_pips[active]
            new_stacks[active] -= contribution #alter the new pips and stacks by the contribution for the active player
            new_pips[active] += contribution
            state = RoundState(self.button + 1, self.street, new_pips, new_stacks, self.hands, self.deck, self) #set updated roundstate object
            return state.proceed_street() #move onto next street
        if isinstance(action, CheckAction):
            if (self.street == 0 and self.button > 0) or self.button > 1:  # both players acted
                return self.proceed_street() #move onto next street
            # otherwise let opponent act
            return RoundState(self.button + 1, self.street, self.pips, self.stacks, self.hands, self.deck, self)
        # isinstance(action, RaiseAction) (only other possibility). Adjust active stack, active pips by the raise amount and let the other player respond
        new_pips = list(self.pips)
        new_stacks = list(self.stacks)
        contribution = action.amount - new_pips[active]
        new_stacks[active] -= contribution
        new_pips[active] += contribution
        return RoundState(self.button + 1, self.street, new_pips, new_stacks, self.hands, self.deck, self)


class Player():
    '''
    Handles subprocess and socket interactions with one player's pokerbot.
    '''

    def __init__(self, name, path):
        self.name = name #set player name
        self.path = path #set player files path
        self.game_clock = STARTING_GAME_CLOCK #set time limit
        self.bankroll = 0 #initally my bankroll is 0 (can go negative)
        self.commands = None 
        self.bot_subprocess = None
        self.socketfile = None
        self.bytes_queue = Queue() #this is for making sure we stay within size limits

    def build(self):
        '''
        Loads the commands file and builds the pokerbot.
        '''
        try: #set the commands we have
            with open(self.path + '/commands.json', 'r') as json_file:
                commands = json.load(json_file)
            if ('build' in commands and 'run' in commands and
                    isinstance(commands['build'], list) and
                    isinstance(commands['run'], list)):
                self.commands = commands
            else:
                print(self.name, 'commands.json missing command')
        except FileNotFoundError:
            print(self.name, 'commands.json not found - check PLAYER_PATH')
        except json.decoder.JSONDecodeError:
            print(self.name, 'commands.json misformatted')
        if self.commands is not None and len(self.commands['build']) > 0: #if we have some commands to build the bot, do them in subprocess
            try:
                proc = subprocess.run(self.commands['build'],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      cwd=self.path, timeout=BUILD_TIMEOUT, check=False)
                self.bytes_queue.put(proc.stdout)
            except subprocess.TimeoutExpired as timeout_expired:
                error_message = 'Timed out waiting for ' + self.name + ' to build'
                print(error_message)
                self.bytes_queue.put(timeout_expired.stdout)
                self.bytes_queue.put(error_message.encode())
            except (TypeError, ValueError):
                print(self.name, 'build command misformatted')
            except OSError:
                print(self.name, 'build failed - check "build" in commands.json')

    def run(self):
        '''
        Runs the pokerbot and establishes the socket connection.
        '''
        if self.commands is not None and len(self.commands['run']) > 0: #if we have commands to run, run in subprocess
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                with server_socket:
                    server_socket.bind(('', 0))
                    server_socket.settimeout(CONNECT_TIMEOUT)
                    server_socket.listen()
                    port = server_socket.getsockname()[1]
                    proc = subprocess.Popen(self.commands['run'] + [str(port)],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            cwd=self.path)
                    self.bot_subprocess = proc
                    # function for bot listening
                    def enqueue_output(out, queue):
                        try:
                            for line in out:
                                queue.put(line)
                        except ValueError:
                            pass
                    # start a separate bot listening thread which dies with the program
                    Thread(target=enqueue_output, args=(proc.stdout, self.bytes_queue), daemon=True).start()
                    # block until we timeout or the player connects
                    client_socket, _ = server_socket.accept()
                    with client_socket:
                        client_socket.settimeout(CONNECT_TIMEOUT)
                        sock = client_socket.makefile('rw')
                        self.socketfile = sock
                        print(self.name, 'connected successfully')
            except (TypeError, ValueError):
                print(self.name, 'run command misformatted')
            except OSError:
                print(self.name, 'run failed - check "run" in commands.json')
            except socket.timeout:
                print('Timed out waiting for', self.name, 'to connect')

    def stop(self):
        '''
        Closes the socket connection and stops the pokerbot.
        '''
        if self.socketfile is not None: #if we have a socketfile
            try:
                self.socketfile.write('Q\n') #write that the game is over
                self.socketfile.close()
            except socket.timeout: #if player takes too long to disconnect
                print('Timed out waiting for', self.name, 'to disconnect')
            except OSError: # if we have system-related error
                print('Could not close socket connection with', self.name)
        if self.bot_subprocess is not None: #if we are using a subprocess for the bot
            try: #try communicating with the subprocess
                outs, _ = self.bot_subprocess.communicate(timeout=CONNECT_TIMEOUT) #get outputs
                self.bytes_queue.put(outs)
            except subprocess.TimeoutExpired: #if it takes too long
                print('Timed out waiting for', self.name, 'to quit')
                self.bot_subprocess.kill() #kill subprocess
                outs, _ = self.bot_subprocess.communicate() #get outputs up to that time
                self.bytes_queue.put(outs)
        with open(self.name + '.txt', 'wb') as log_file: #write player log file
            bytes_written = 0
            for output in self.bytes_queue.queue:
                try:
                    bytes_written += log_file.write(output)
                    if bytes_written >= PLAYER_LOG_SIZE_LIMIT: #keep writing until we reach limit
                        break
                except TypeError: #if we cant write the output then skip it
                    pass
        

    def query(self, round_state, player_message, game_log):
        '''
        Requests one action from the pokerbot over the socket connection.
        At the end of the round, we request a CheckAction from the pokerbot.
        '''
        legal_actions = round_state.legal_actions() if isinstance(round_state, RoundState) else {CheckAction} #get the possible legal actions
        if self.socketfile is not None and self.game_clock > 0.: #if we can communicate and there is still time
            try:
                player_message[0] = 'T{:.3f}'.format(self.game_clock)
                message = ' '.join(player_message) + '\n'
                del player_message[1:]  # do not send redundant action history
                start_time = time.perf_counter() #start timer
                
                self.socketfile.write(message) # write gameclock to socketfile
                self.socketfile.flush() #commit that change
                clause = self.socketfile.readline().strip() #get rid of the spaces and read the top line
                end_time = time.perf_counter() #end timer
                if ENFORCE_GAME_CLOCK: #if we are timing, change the game clock
                    self.game_clock -= end_time - start_time
                if self.game_clock <= 0.:
                    raise socket.timeout #socket timed out :|
                action = DECODE[clause[0]] #decode the letter to the action
                if action in legal_actions:
                    if clause[0] == 'R': #if we are raising, and the raise is within bounds, then do it, otherwise check/fold
                        amount = int(clause[1:])
                        min_raise, max_raise = round_state.raise_bounds()
                        if min_raise <= amount <= max_raise:
                            return action(amount)
                    else: #otherwise, we have 'C' or 'F' so just do that 
                        return action()
                game_log.append(self.name + ' attempted illegal ' + action.__name__) #if we tried an illegal action, put that in log
            except socket.timeout: #if we timed out, put in log and set clock to 0
                error_message = self.name + ' ran out of time'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except OSError: #if we have system-related error, put in log and set clock to 0
                error_message = self.name + ' disconnected'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except (IndexError, KeyError, ValueError): #if we misformat our response
                game_log.append(self.name + ' response misformatted')
        return CheckAction() if CheckAction in legal_actions else FoldAction() #default move is check/fold

        


class Game():
    '''
    Manages logging and the high-level game procedure.
    '''

    def __init__(self):
        self.log = ['Cambridge University Algorithmic Games Society - AlgoPoker - ' + PLAYER_1_NAME + ' vs ' + PLAYER_2_NAME,
                    '---------------------------'
                    ]
        self.player_messages = [[], []]

    
    def log_round_state(self, players, round_state):
        '''
        Incorporates RoundState information into the game log and player messages.
        '''
        if round_state.street == 0 and round_state.button == 0: #log pre flop blinds posted and cards dealt
            self.log.append('{} posts the blind of {}'.format(players[0].name, SMALL_BLIND))
            self.log.append('{} posts the blind of {}'.format(players[1].name, BIG_BLIND))
            self.log.append('{} dealt {}'.format(players[0].name, PCARDS(round_state.hands[0])))
            self.log.append('{} dealt {}'.format(players[1].name, PCARDS(round_state.hands[1])))
            self.player_messages[0] = ['T0.', 'P0', 'H' + CCARDS(round_state.hands[0])]
            self.player_messages[1] = ['T0.', 'P1', 'H' + CCARDS(round_state.hands[1])]
        elif round_state.street > 0 and round_state.button == 1: #log cards on board and stack sizes
            board = round_state.deck.peek(round_state.street)
            self.log.append(STREET_NAMES[round_state.street - 3] + ' ' + PCARDS(board) +
                            PVALUE(players[0].name, STARTING_STACK-round_state.stacks[0]) +
                            PVALUE(players[1].name, STARTING_STACK-round_state.stacks[1]))
            compressed_board = 'B' + CCARDS(board)
            self.player_messages[0].append(compressed_board)
            self.player_messages[1].append(compressed_board)

    def log_action(self, name, action, bet_override): #log player actions
        '''
        Incorporates action information into the game log and player messages.
        '''
        if isinstance(action, FoldAction):
            phrasing = ' folds'
            code = 'F'
        elif isinstance(action, CallAction):
            phrasing = ' calls'
            code = 'C'
        elif isinstance(action, CheckAction):
            phrasing = ' checks'
            code = 'K'
        else:  # isinstance(action, RaiseAction)
            phrasing = (' bets ' if bet_override else ' raises to ') + str(action.amount) #bet_override just phrases correctly
            code = 'R' + str(action.amount)
        self.log.append(name + phrasing)
        self.player_messages[0].append(code)
        self.player_messages[1].append(code)
    def log_terminal_state(self, players, round_state): #logs if at showdown and logs who was awarded what in any case
        '''
        Incorporates TerminalState information into the game log and player messages.
        '''
        previous_state = round_state.previous_state
        if FoldAction not in previous_state.legal_actions():
            self.log.append('{} shows {}'.format(players[0].name, PCARDS(previous_state.hands[0])))
            self.log.append('{} shows {}'.format(players[1].name, PCARDS(previous_state.hands[1])))
            self.player_messages[0].append('O' + CCARDS(previous_state.hands[1]))
            self.player_messages[1].append('O' + CCARDS(previous_state.hands[0]))
        self.log.append('{} awarded {}'.format(players[0].name, round_state.deltas[0]))
        self.log.append('{} awarded {}'.format(players[1].name, round_state.deltas[1]))
        self.player_messages[0].append('D' + str(round_state.deltas[0]))
        self.player_messages[1].append('D' + str(round_state.deltas[1]))

    def run_round(self, players):
        '''
        Runs one round of poker.
        '''

        deck = eval7.Deck() #fresh deck of cards
        deck.shuffle() #shuffle this deck
        hands = [deck.deal(2), deck.deal(2)] #each player gets 2 cards
        pips = [SMALL_BLIND, BIG_BLIND] #first player in list small blind, second player big blind (we sorted out reversing in Game)
        stacks = [STARTING_STACK - SMALL_BLIND, STARTING_STACK - BIG_BLIND] #reflect pips in stack (same starting stack each time)
        round_state = RoundState(0, 0, pips, stacks, hands, deck, None) #button set to 0 for initial move by sb, preflop, pips, stack,hands,deck as above
        while not isinstance(round_state, TerminalState): #while we are not at end
            self.log_round_state(players, round_state) #log at start of each round
            active = round_state.button % 2 #active player is number of alternations mod 2
            player = players[active]
            action = player.query(round_state, self.player_messages[active], self.log) #ask the active player to move, send them the relevent info and a copy of the log
            bet_override = (round_state.pips == [0, 0]) #do we say bet or raise in log
            self.log_action(player.name, action, bet_override)
            round_state = round_state.proceed(action) #advance game tree by the action that just came
        self.log_terminal_state(players, round_state)
        for player, player_message, delta in zip(players, self.player_messages, round_state.deltas):
            player.query(round_state, player_message, self.log) #tell player the outcome
            player.bankroll += delta #adjust bankroll by change 
        

    def run(self):
        '''
        Runs one game of poker.
        '''
        '''
        Runs one game of poker.
        '''

        print('''
░█████╗░██╗░░░░░░██████╗░░█████╗░██████╗░░█████╗░██╗░░██╗███████╗██████╗░
██╔══██╗██║░░░░░██╔════╝░██╔══██╗██╔══██╗██╔══██╗██║░██╔╝██╔════╝██╔══██╗
███████║██║░░░░░██║░░██╗░██║░░██║██████╔╝██║░░██║█████═╝░█████╗░░██████╔╝
██╔══██║██║░░░░░██║░░╚██╗██║░░██║██╔═══╝░██║░░██║██╔═██╗░██╔══╝░░██╔══██╗
██║░░██║███████╗╚██████╔╝╚█████╔╝██║░░░░░╚█████╔╝██║░╚██╗███████╗██║░░██║
╚═╝░░╚═╝╚══════╝░╚═════╝░░╚════╝░╚═╝░░░░░░╚════╝░╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝''')
        print()
        print('Starting the AlgoPoker engine...')
        players = [
            Player(PLAYER_1_NAME, PLAYER_1_PATH),
            Player(PLAYER_2_NAME, PLAYER_2_PATH)
        ] #list of player objects
        for player in players: #initialise each player bot
            player.build()
            player.run()
        for round_num in range(1, NUM_ROUNDS + 1): #loop each round, logging then reverse list for blinds
            self.log.append('')
            self.log.append('Round #' + str(round_num) + STATUS(players))
            self.run_round(players)
            players = players[::-1]
        #log at the end
        self.log.append('')
        self.log.append('')
        self.log.append('Final' + STATUS(players))
        for player in players:
            player.stop()
        name = GAME_LOG_FILENAME + '.txt'
        print('Writing', name)
        with open(name, 'w') as log_file:
            log_file.write('\n'.join(self.log))


if __name__ == '__main__':
    Game().run()