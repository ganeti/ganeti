{-| Module abstracting the node and instance container implementation.

This is currently implemented on top of an 'IntMap', which seems to
give the best performance for our workload.

-}

module Ganeti.HTools.Container
    (
     -- * Types
     Container
     -- * Creation
    , empty
    , fromAssocList
     -- * Query
    , size
    , find
     -- * Update
    , add
    , addTwo
    , remove
    -- * Conversion
    , elems
    , keys
    ) where

import qualified Data.IntMap as IntMap

type Key = IntMap.Key
type Container = IntMap.IntMap

-- | Create an empty container.
empty :: Container a
empty = IntMap.empty

-- | Returns the number of elements in the map.
size :: Container a -> Int
size = IntMap.size

-- | Locate a key in the map (must exist).
find :: Key -> Container a -> a
find k c = c IntMap.! k

-- | Locate a keyin the map returning a default value if not existing.
findWithDefault :: a -> Key -> Container a -> a
findWithDefault = IntMap.findWithDefault

-- | Add or update one element to the map.
add :: Key -> a -> Container a -> Container a
add k v c = IntMap.insert k v c

-- | Remove an element from the map.
remove :: Key -> Container a -> Container a
remove = IntMap.delete

-- | Return the list of values in the map.
elems :: Container a -> [a]
elems = IntMap.elems

-- | Return the list of keys in the map.
keys :: Container a -> [Key]
keys = IntMap.keys

-- | Create a map from an association list.
fromAssocList :: [(Key, a)] -> Container a
fromAssocList = IntMap.fromList

-- | Create a map from an association list with a combining function.
fromListWith :: (a -> a -> a) -> [(Key, a)] -> Container a
fromListWith = IntMap.fromListWith

-- | Fold over the values of the map.
fold :: (a -> b -> b) -> b -> Container a -> b
fold = IntMap.fold

-- | Add or update two elements of the map.
addTwo :: Key -> a -> Key -> a -> Container a -> Container a
addTwo k1 v1 k2 v2 c = add k1 v1 $ add k2 v2 c
