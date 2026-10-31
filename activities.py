"""Offline buddy interactions, independent of the Windows message loop."""
from dataclasses import dataclass
import random


def greeting(hour):
    if 5<=hour<11:return '早上好，你。今天也慢慢来。'
    if 11<=hour<17:return '喵帕斯～你，午后也一起待着吧。'
    if 17<=hour<23:return '晚上好，你。咱在这里陪你。'
    return '夜深啦，你。咱小声一点陪着你。'


@dataclass
class Activities:
    affection: int=0
    touches: int=0
    follow: bool=False
    rest_minutes: int=0
    rest_due: float=0.
    game_open: bool=False
    opponent: int=0

    def pet(self):
        self.touches+=1
        self.affection=min(100,self.affection+2)

    def feed(self):
        self.touches+=1
        self.affection=min(100,self.affection+3)

    def start_game(self,rng=None):
        self.game_open=True
        self.opponent=(rng or random).randrange(3)

    def choose(self,player):
        if not self.game_open or player not in (0,1,2):return None
        self.game_open=False
        outcome=(player-self.opponent)%3
        return self.opponent,('draw' if outcome==0 else 'win' if outcome==2 else 'lose')

    def reminder(self,minutes,now):
        self.rest_minutes=minutes if minutes in (0,25,50) else 0
        self.rest_due=now+self.rest_minutes*60 if self.rest_minutes else 0.

    def poll(self,now,available):
        if self.rest_minutes and available and now>=self.rest_due:
            self.rest_due=now+self.rest_minutes*60
            return True
        return False

    @staticmethod
    def follow_direction(center,target,deadzone):
        if target>center+deadzone:return 1
        if target<center-deadzone:return -1
        return 0
