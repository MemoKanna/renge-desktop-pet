"""Time and distance based animation, independent of the window renderer."""
from dataclasses import dataclass, field
import math
from action_rig import PET_DURATION, POUNCE_DURATION, pounce_travel


@dataclass
class Motion:
    size: int = 300
    state: str = 'idle'
    direction: int = 1
    age: float = 0.0
    gait: float = 0.0
    speed: float = 0.0
    flute_seconds: float = 8.0
    events: list = field(default_factory=list)
    stop_requested: bool = False
    turn_flipped: bool = False
    stride_ratio: float = .28
    expression: int = 0
    pet_held: bool = False

    def enter(self, state):
        if self.state.startswith('flute') and not state.startswith('flute'):
            self.events.append('audio_stop')
        self.state, self.age = state, 0.0
        if state != 'pet': self.pet_held = False
        if state != 'walk':
            self.speed = 0.0

    def walk(self, direction=None):
        if direction:
            self.direction = 1 if direction > 0 else -1
        self.enter('walk')
        self.stop_requested = False

    def stop(self):
        if self.state == 'walk':
            self.stop_requested = True
        elif self.state.startswith('flute'):
            self.events.append('audio_stop')
            self.enter('flute_out')
        else:
            self.enter('idle')

    def turn(self):
        if self.state == 'walk':
            self.enter('turn')
            self.turn_flipped = False

    def greet(self):
        self.enter('greet')

    def pet(self, held=False):
        self.enter('pet')
        self.pet_held=held

    def release_pet(self):
        if self.state=='pet' and self.pet_held:
            self.age=self.pet_sample_age()
            self.pet_held=False

    def pet_sample_age(self):
        return .8+(self.age-.8)%1.6 if self.pet_held and self.age>.8 else self.age

    def emote(self, expression):
        self.expression=max(0,min(7,expression))
        self.enter('emote')

    def pounce(self, direction=1):
        self.direction=1 if direction>=0 else -1
        self.enter('pounce')

    def sleep(self):
        self.enter('sleep_in')

    def wake(self):
        self.enter('wake')

    def flute(self):
        if self.state.startswith('flute'):
            self.stop()
        else:
            self.enter('flute_in')

    def drag(self):
        self.enter('drag')

    def update(self, dt):
        dt = max(0.0, min(dt, .1))
        previous_age=self.age
        self.age += dt
        distance = 0.0
        if self.state == 'walk':
            target = 0 if self.stop_requested else self.size * .18
            acceleration = self.size * .45
            step = acceleration * dt
            previous = self.speed
            self.speed += min(step, max(-step, target - self.speed))
            distance = (previous + self.speed) * .5 * dt
            self.gait = (self.gait + distance / (self.size * self.stride_ratio)) % 1
            if self.stop_requested and self.speed <= .01:
                self.gait = 0
                self.enter('idle')
            return distance * self.direction
        if self.state == 'turn':
            if self.age >= .15 and not self.turn_flipped:
                self.direction *= -1
                self.turn_flipped = True
            if self.age >= .32:
                self.gait = 0
                self.walk()
        elif self.state == 'greet' and self.age >= 2.1:
            self.enter('idle')
        elif self.state == 'pet' and not self.pet_held and self.age >= PET_DURATION:
            self.enter('idle')
        elif self.state == 'emote' and self.age>=3.6:
            self.enter('idle')
        elif self.state == 'pounce':
            distance=(pounce_travel(self.age)-pounce_travel(previous_age))*self.size*.70*self.direction
            if self.age>=POUNCE_DURATION:self.enter('idle')
            return distance
        elif self.state == 'sleep_in' and self.age >= .5:
            self.enter('sleep')
        elif self.state == 'wake' and self.age >= .55:
            self.enter('idle')
        elif self.state == 'flute_in' and self.age >= .55:
            self.enter('flute_play')
            self.events.append('audio_start')
        elif self.state == 'flute_play' and self.age >= self.flute_seconds:
            self.events.append('audio_stop')
            self.enter('flute_out')
        elif self.state == 'flute_out' and self.age >= .55:
            self.enter('idle')
        return 0.0

    def drain_events(self):
        events, self.events = self.events, []
        return events

    def frame(self):
        """Return atlas, cell, flip; gait advances only with actual displacement."""
        state, age = self.state, self.age
        if state == 'walk':
            return 'walk', int(self.gait * 8) % 8, self.direction < 0
        if state == 'turn':
            return 'walk', 0, self.direction < 0
        if state == 'greet':
            steps = (3, 4, 4, 5, 4, 5, 4, 5, 4, 3)
            return 'base', steps[min(len(steps) - 1, int(age / 2.1 * len(steps)))], False
        if state == 'pet':
            return 'base',2 if .2<age<1.1 else 0,False
        if state == 'sleep_in':
            return 'base', 2 if age < .15 else 6, False
        if state == 'sleep':
            return 'base', 6 if int(age / 2.1) % 2 == 0 else 7, False
        if state == 'wake':
            return 'base', 6 if age < .2 else (2 if age < .3 else 0), False
        if state == 'flute_in':
            return 'flute', min(2, int(age / .55 * 3)), False
        if state == 'flute_play':
            sequence = (3, 4, 5, 4, 3, 5, 4, 6)
            return 'flute', sequence[int(age * 4) % len(sequence)], False
        if state == 'flute_out':
            return 'flute', 7 if age < .2 else (1 if age < .35 else 0), False
        if state == 'drag':
            return 'base', 1, False
        return 'base', 0, False

    def sample(self):
        """Two registered key poses and their continuous time/distance mix."""
        state, age = self.state, self.age

        def timeline(atlas, keys, position, mirror=False):
            position = max(0., min(len(keys) - 1., position))
            first = int(position)
            second = min(len(keys) - 1, first + 1)
            return atlas, keys[first], keys[second], position - first, mirror

        if state == 'walk':
            position = self.gait * 8
            index = int(position) % 8
            return 'walk', index, (index + 1) % 8, position % 1, self.direction < 0
        if state == 'turn':
            return 'walk', 0, 0, 0., self.direction < 0
        if state == 'greet':
            keys = (0, 3, 4, 5, 4, 5, 4, 3, 0)
            return timeline('base', keys, age / 2.1 * (len(keys) - 1))
        if state == 'pet':
            return 'pet',0,0,self.pet_sample_age(),False
        if state=='emote':
            return 'emote',self.expression,0,age,False
        if state=='pounce':
            return 'pounce',0,0,age,self.direction<0
        if state == 'sleep_in':
            return timeline('base', (0, 2, 6), age / .5 * 2)
        if state == 'sleep':
            return timeline('base', (6, 7, 6), (age % 5.) / 5. * 2)
        if state == 'wake':
            return timeline('base', (6, 2, 0), age / .55 * 2)
        if state == 'flute_in':
            return timeline('flute', (0, 1, 2, 3), age / .55 * 3)
        if state == 'flute_play':
            # Complete phrase loops back through adjacent finger poses, with
            # no independent hair/head frame changes (renderer shares them).
            keys = (3, 4, 5, 4, 3, 5, 4, 6, 3)
            return timeline('flute', keys, (age % 2.4) / 2.4 * (len(keys) - 1))
        if state == 'flute_out':
            return timeline('flute', (3, 2, 1, 0), age / .55 * 3)
        if state == 'drag':
            return 'base', 1, 1, 0., False
        return 'base', 0, 0, 0., False


def breathing(age, size, sleeping=False):
    return math.sin(age * (1.8 if sleeping else 2.1)) * min(.6, size * .002)
