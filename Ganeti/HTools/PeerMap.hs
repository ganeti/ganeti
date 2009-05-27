{-|
  Module abstracting the peer map implementation.

This is abstracted separately since the speed of peermap updates can
be a significant part of the total runtime, and as such changing the
implementation should be easy in case it's needed.

-}

module Ganeti.HTools.PeerMap
    (
     PeerMap,
     Key,
     Elem,
     empty,
     create,
     accumArray,
     Ganeti.HTools.PeerMap.find,
     add,
     remove,
     maxElem
    ) where

import Data.Maybe (fromMaybe)
import Data.List
import Data.Function
import Data.Ord

import Ganeti.HTools.Types

type Key = Ndx
type Elem = Int
type PeerMap = [(Key, Elem)]

empty :: PeerMap
empty = []

create :: Key -> PeerMap
create _ = []

-- | Our reverse-compare function
pmCompare :: (Key, Elem) -> (Key, Elem) -> Ordering
pmCompare a b = (compare `on` snd) b a

-- | Add or update (via a custom function) an element
addWith :: (Elem -> Elem -> Elem) -> Key -> Elem -> PeerMap -> PeerMap
addWith fn k v lst =
    let r = lookup k lst
    in
      case r of
        Nothing -> insertBy pmCompare (k, v) lst
        Just o -> insertBy pmCompare (k, fn o v) (remove k lst)

-- | Create a PeerMap from an association list, with possible duplicates
accumArray :: (Elem -> Elem -> Elem) -- ^ function used to merge the elements
              -> [(Key, Elem)]       -- ^ source data
              -> PeerMap             -- ^ results
accumArray fn lst =
    case lst of
      [] -> empty
      (k, v):xs -> addWith fn k v $ accumArray fn xs

find :: Key -> PeerMap -> Elem
find k c = fromMaybe 0 $ lookup k c

add :: Key -> Elem -> PeerMap -> PeerMap
add k v c = addWith (\_ n -> n) k v c

remove :: Key -> PeerMap -> PeerMap
remove k c = case c of
               [] -> []
               (x@(x', _)):xs -> if k == x' then xs
                            else x:(remove k xs)

to_list :: PeerMap -> [Elem]
to_list c = snd $ unzip c

maxElem :: PeerMap -> Elem
maxElem c = case c of
              [] -> 0
              (_, v):_ -> v
