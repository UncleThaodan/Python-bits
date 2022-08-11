from __future__ import annotations
from typing import Iterable, Iterator, Optional, TYPE_CHECKING
import numpy as np  # type: ignore
from tcod.console import Console

from entity import Actor, Item
import tile_types

if TYPE_CHECKING:
    from engine import Engine
    from entity import Entity

class GameMap:
    def __init__(self,
        engine: Engine,
        width: int,
        height: int,
        entities: Iterable[Entity] = ()
    ):
        self.engine = engine
        self.width, self.height = width, height
        self.entities = set(entities)
        self.tiles = np.full((width, height), fill_value = tile_types.wall, order='F') # numpy filled with wall tiles in fortran order

        self.visible = np.full(
            (width, height), fill_value = False, order = "F"
        ) # tiles the player can see currently

        self.explored = np.full(
            (width, height), fill_value = False, order = "F"
        ) # tiles the player has seen already

        self.downstairs_location = (0, 0)

    @property
    def gamemap(self) -> GameMap:
        return self

    @property
    def area(self):
        return self.width * self.height

    @property
    def actors(self) -> Iterator[Actor]:
        yield from (
            entity
            for entity in self.entities
            if isinstance(entity, Actor) and entity.is_alive
        )

    @property
    def items(self) -> Iterator[Item]:
        yield from (entity for entity in self.entities if isinstance(entity, Item))

    # check list of entities and return one being at [x, y] location
    def get_blocking_entity_at_location(self, location_x: int, location_y: int) -> Optional[Entity]:
        for entity in self.entities:
            if (
                entity.blocks_movement
                and entity.x == location_x
                and entity.y == location_y
            ):
                return entity

        return None

    def get_actor_at_location(self, x: int, y: int) -> Optional[Actor]:
        for actor in self.actors:
            if actor.x == x and actor.y == y:
                return actor

        return None

    # check if given coordinates are within bounds of game map
    def in_bounds(self, x: int, y: int) -> bool:
        # Return True if x and y are inside of the bounds of this map.
        return 0 <= x < self.width and 0 <= y < self.height

    def render(self, console: Console) -> None:
        # prints the whole map, its called from within Engine when we render every bit to console
        # print based on condition whether tiles are visible or were explored already
        # if not, default to SHROUDed tile, which is just empty black square
        console.tiles_rgb[0 : self.width, 0 : self.height] = np.select(
            condlist = [self.visible, self.explored],
            choicelist = [self.tiles["light"], self.tiles["dark"]],
            default = tile_types.SHROUD,
        )

        # sorted list of entities to render on gamemap, based on order value
        entities_for_rendering = sorted(
            self.entities, key = lambda x: x.render_order.value
        )

        # display whole map without FOV function
        console.tiles_rgb[0:self.width, 0:self.height] = self.tiles["light"]

        for entity in entities_for_rendering:
            # don't apply FOV to entites
            console.print(x = entity.x, y = entity.y, string = entity.char, fg = entity.color)
            # display entity only if in FOV
            # if self.visible[entity.x, entity.y]:
            #     console.print(
            #         x = entity.x, y = entity.y, string = entity.char, fg = entity.color
            #     )

class GameWorld:
    """Holds settings for GameMap and generates new maps when dwelling deeper down"""

    def __init__(
        self,
        *,
        engine: Engine,
        map_width: int,
        map_height: int,
        initial_open: float,
        max_monsters: int,
        max_items: int,
        current_floor: int = 0
    ):
        self.engine = engine

        self.map_width = map_width
        self.map_height = map_height
        self.initial_open = initial_open

        self.max_monsters = max_monsters
        self.max_items = max_items

        self.current_floor = current_floor

    def generate_floor(self) -> None:
        from procgen import generate_dungeon

        self.current_floor += 1

        self.engine.game_map = generate_dungeon(
            map_width = self.map_width,
            map_height = self.map_height,
            initial_open = self.initial_open,
            max_monsters = self.max_monsters,
            max_items = self.max_items,
            engine = self.engine,
        )