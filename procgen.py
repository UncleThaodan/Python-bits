from __future__ import annotations
from copy import deepcopy
from tcod import los

from random import choices, randrange, randint, seed
from typing import Dict, Tuple, List, Iterator, TYPE_CHECKING
from scipy import signal

import numpy as np
import components
from engine import Engine

from game_map import GameMap
import tile_types
import entity_factories

if TYPE_CHECKING:
    from engine import Engine
    from entity import Entity

int_seed = 0
base_seed = 'ragnis'
for ch in base_seed:
    int_seed <<= 8 + ord(ch)

seed(int_seed)

nprng = np.random.default_rng(int_seed)

# tuples that contain information (floor number, maximum amount of entity type)
# used for generating amount of said entities based on current floor level
max_items_per_floor = [
    (1, 1),
    (4, 2),
    (6, 3),
]
max_monsters_per_floor = [
    (1, 2),
    (4, 3),
    (6, 5),
]

# dictionaires of weighted entites for spawning
# higher weight means higher chance of spawning
# dict key is the floor number where they start appearing
item_chances: Dict[int, List[Tuple[Entity, int]]] = {
    0: [(entity_factories.health_potion, 35),
        (entity_factories.power_ring, 5),
        (entity_factories.defense_ring, 5),
        (entity_factories.goblin, 50)],
    2: [(entity_factories.confusion_scroll, 10)],
    4: [(entity_factories.lightning_scroll, 25),
        (entity_factories.sword, 10),
        (entity_factories.power_ring, 5),
        (entity_factories.defense_ring, 5)],
    6: [(entity_factories.fireball_scroll, 25),
        (entity_factories.chain_mail, 10),
        (entity_factories.omni_ring, 5)],
    9: [(entity_factories.health_potion, 20),
        (entity_factories.chain_mail, 10),
        (entity_factories.confusion_scroll, 20)]
}

enemy_chances: Dict[int, List[Tuple[Entity, int]]] = {
    0: [(entity_factories.orc, 80)],
    3: [(entity_factories.troll, 15)],
    5: [(entity_factories.troll, 30)],
    7: [(entity_factories.orc, 25),
        (entity_factories.troll, 45)],
}

# helper kernel for convolve2d, basically 2d array [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
kernel = np.ones((3, 3), dtype = 'int')
kernel[1, 1] = 0

def get_max_value_for_floor(
    max_value: List[Tuple[int, int]], floor: int
) -> int:
    current_value = 0

    for floor_minimum, value in max_value:
        if floor_minimum > floor:
            break
        else:
            current_value = value

    return current_value

def get_entities_at_random(
    weighted_chance_by_floor: Dict[int, List[Tuple[Entity, int]]],
    number_of_entities: int,
    floor: int,
) -> List[Entity]:
    entity_weighted_chances = {}

    for key, values in weighted_chance_by_floor.items():
        if key > floor:
            break
        else:
            for value in values:
                entity = value[0]
                weighted_chance = value[1]

                entity_weighted_chances[entity] = weighted_chance

    entities = list(entity_weighted_chances.keys())
    entity_weighted_chance_values = list(entity_weighted_chances.values())

    chosen_entities = choices(
        entities, weights = entity_weighted_chance_values, k = number_of_entities
    )

    return chosen_entities

def place_entities(dungeon: GameMap, floor_number: int) -> None:
    number_of_monsters = randint(
        0, get_max_value_for_floor(max_monsters_per_floor, floor_number)
    )
    number_of_items = randint(
        0, get_max_value_for_floor(max_items_per_floor, floor_number)
    )

    # select random postion for enemy using numpy.where
    # we look only at positions that are floors,
    # this way we avoid placing the enemies in walls,
    # and we don't need more complicated checks
    x, y = np.where(dungeon.tiles['walkable'])

    monsters: List[Entity] = get_entities_at_random(
        enemy_chances, number_of_monsters, floor_number
    )
    items: List[Entity] = get_entities_at_random(
        item_chances, number_of_items, floor_number
    )

    for entity in monsters + items:
        # we generate random integer from tiles we found as viable
        # it's used later to select given index in the game_map array
        j = nprng.integers(len(x))

        # check if the selected spot doesn't contain any entity already
        # if it does not then place one of the monsters
        # 80% chance for orc 20% for troll
        if not any(entity.x == x[j] and entity.y == y[j] for entity in dungeon.entities):
            entity.spawn(dungeon, x[j], y[j])
            if entity is entity_factories.goblin:
                entity_factories.sword.spawn(dungeon, x[j] - 2, y[j])
                entity_factories.health_potion.spawn(dungeon, x[j] - 1, y[j] - 2)
            print(f'Placed {entity.name} at: ', x[j], y[j])

    j = nprng.integers(len(x))

    # insert stairs going down the level
    dungeon.tiles[x[j], y[j]] = tile_types.down_stairs
    dungeon.downstairs_location = (x[j], y[j])
    # insert stairs going up level
    # dungeon.tiles[x[j + 1], y[j + 1]] = tile_types.up_stairs
    # dungeon.upstairs_location = (x[j + 1], y[j + 1])

# in future it wll take all gamemap objects (not Actors!)
# and turn some into mimics, or not
def make_mimic(dungeon: GameMap):
    target = dungeon.get_actor_at_location(40, 21)
    target.ai = components.ai.MimicHostileEnemy(
        entity = target, message = False, origin_x = target.x, origin_y = target.y
    )

def dig_vertically(map: GameMap, x: int, y1: int, y2: int):
    # dig a vertical tunnel
    for y in range(min(y1, y2), max(y1, y2) + 1):
        if x > 0 and x < map.width - 1 and y > 0 and y < map.height - 1:
            map.tiles[x, y] = tile_types.floor

def dig_horizontally(map: GameMap, y: int, x1: int, x2: int):
    # dig a horizontal tunnel
    for x in range(min(x1, x2), max(x1, x2) + 1):
        if x > 0 and x < map.width - 1 and y > 0 and y < map.height - 1:
            map.tiles[x, y] = tile_types.floor

def cellular_automata(dungeon: GameMap, min: int, max: int, count: GameMap):
    # on each pass we recalculate amount of neighbours, which gives much smoother output
    # more passes equals smoother map and less artifacts
    count = signal.convolve2d(dungeon.tiles['value'], kernel, mode = 'same', boundary = 'wrap')
    for i in range(1, dungeon.width - 1):
        for j in range(1, dungeon.height - 1):
            # if in the cell neighbourhood is at least MAX floors
            # then it 'dies' and turns into floor
            if count[i, j] > max:
                dungeon.tiles[i, j] = tile_types.floor
            # same rule applies to floor cells, if they have less than MIN floors
            # in neighbourhood, turn them into wall
            elif count[i, j] < min:
                dungeon.tiles[i, j] = tile_types.wall

    return dungeon

class RectangularRoom:
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x1 = x
        self.y1 = y
        self.x2 = x + width
        self.y2 = y + height

    @property
    def center(self) -> Tuple[int, int]:
        center_x = int((self.x1 + self.x2) / 2)
        center_y = int((self.y1 + self.y2) / 2)

        return center_x, center_y

    # return inside of the room, not counting the walls
    @property
    def inner(self) -> Tuple[slice, slice]:
        return slice(self.x1 + 1, self.x2), slice(self.y1 + 1, self.y2)

    def intersects(self, other: RectangularRoom) -> bool:
        return(
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )

def tunnel_between(start: Tuple[int, int], end: Tuple[int, int]) -> Iterator[Tuple[int, int]]:
    # return L shaped tunnel between two points
    x1, y1 = start
    x2, y2 = end

    if nprng.random() < 0.5:
        # go horizontal, then vertical
        corner_x, corner_y = x2, y1
    else:
        # go vertical, then horizontal
        corner_x, corner_y = x1, y2

    for x, y in los.bresenham((x1, y1), (corner_x, corner_y)).tolist():
        yield x, y
    for x, y in los.bresenham((corner_x, corner_y), (x2, y2)).tolist():
        yield x, y

def generate_rooms(
    dungeon: GameMap,
    max_rooms: int,
    room_min_size: int,
    room_max_size: int,
) -> List[Tuple[int, int, int, int]]:

    rooms: List[RectangularRoom] = []

    for r in range(max_rooms):
        # random width and height
        w = nprng.integers(room_min_size, room_max_size)
        h = nprng.integers(room_min_size, room_max_size)

        # random position within map bounds
        x = nprng.integers(0, dungeon.width - w - 1)
        y = nprng.integers(0, dungeon.height - h - 1)

        new_room = RectangularRoom(x, y, w, h)

        # check for intersection with other rooms
        if any(new_room.intersects(other_room) for other_room in rooms):
            continue # intersects go next room
        # if not then room is valid

        # dig out the room
        # top and bottom wall
        dungeon.tiles[x:x+w, y] = tile_types.wall
        dungeon.tiles[x:x+w +1, y+h] = tile_types.wall
        # left and right wall
        dungeon.tiles[x, y:y+h] = tile_types.wall
        dungeon.tiles[x+w, y:y+h] = tile_types.wall
        dungeon.tiles[new_room.inner] = tile_types.floor

        if len(rooms) == 0:
            # spawn player in first room
            (player_x, player_y) = new_room.center
            dungeon.engine.player.place(player_x, player_y, dungeon)
        else:
            # dig out tunnels for the current room and the previous one, we don't do it for first, as it has no room previous to it
            for x, y in tunnel_between(rooms[-1].center, new_room.center):
                dungeon.tiles[x, y] = tile_types.floor

        # we add the new room to our list of rooms
        rooms.append(new_room)

    return dungeon

def generate_dungeon(
    map_width: int,
    map_height: int,
    initial_open: int,
    engine: Engine,
) -> GameMap:
    # Generate a new dungeon map.
    player = engine.player
    dungeon = GameMap(engine, map_width, map_height, entities = [player])
    # helper map to hold convolve calculation
    wall_count = GameMap(engine, map_width, map_height)

    # number of fields to 'open' or replace/carve out with floors
    open_count = (dungeon.area * initial_open)

    # randomly selected tile gets replaced with floor/carved out
    while open_count > 0:
        rand_w = randrange(1, dungeon.width - 1)
        rand_h = randrange(1, dungeon.height - 1)

        if dungeon.tiles[rand_w, rand_h] == tile_types.wall:
            dungeon.tiles[rand_w, rand_h] = tile_types.floor
            open_count -= 1

    # we go through the map and simulate cellular automata rules using convolve values
    # we do two passes with alternate ruleset to achieve both open spaces and tight corridors
    for x in range(1):
        cellular_automata(dungeon, 3, 4, wall_count)
        cellular_automata(dungeon, 4, 5, wall_count)

    # x, y = np.where(dungeon.tiles["walkable"])
    # j = nprng.integers(len(x))
    # player.place(x[j], y[j], dungeon)

    generate_rooms(dungeon, 6, 4, 6)

    place_entities(dungeon, engine.game_world.current_floor)

    return dungeon