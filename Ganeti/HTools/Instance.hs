{-| Module describing an instance.

The instance data type holds very few fields, the algorithm
intelligence is in the "Node" and "Cluster" modules.

-}
module Ganeti.HTools.Instance where

import qualified Ganeti.HTools.Types as T
import qualified Ganeti.HTools.Container as Container

-- * Type declarations

-- | The instance type
data Instance = Instance { name :: String   -- ^ The instance name
                         , mem :: Int       -- ^ Memory of the instance
                         , dsk :: Int       -- ^ Disk size of instance
                         , running :: Bool  -- ^ Whether the instance
                                            -- is running
                         , run_st :: String -- ^ Original (text) run status
                         , pnode :: T.Ndx   -- ^ Original primary node
                         , snode :: T.Ndx   -- ^ Original secondary node
                         , idx :: T.Idx     -- ^ Internal index for
                                            -- book-keeping
                         } deriving (Show)

instance T.Element Instance where
    nameOf  = name
    idxOf   = idx
    setName = setName
    setIdx  = setIdx

-- | A simple name for the int, instance association list.
type AssocList = [(T.Idx, Instance)]

-- | A simple name for an instance map.
type List = Container.Container Instance

-- * Initialization

-- | Create an instance.
--
-- Some parameters are not initialized by function, and must be set
-- later (via 'setIdx' for example).
create :: String -> Int -> Int -> String -> T.Ndx -> T.Ndx -> Instance
create name_init mem_init dsk_init run_init pn sn =
    Instance {
          name = name_init,
          mem = mem_init,
          dsk = dsk_init,
          running = case run_init of
                      "running" -> True
                      "ERROR_up" -> True
                      _ -> False,
          run_st = run_init,
          pnode = pn,
          snode = sn,
          idx = -1
        }

-- | Changes the index.
--
-- This is used only during the building of the data structures.
setIdx :: Instance  -- ^ the original instance
        -> T.Idx    -- ^ new index
        -> Instance -- ^ the modified instance
setIdx t i = t { idx = i }

-- | Changes the name.
--
-- This is used only during the building of the data structures.
setName :: Instance -- ^ The original instance
        -> String   -- ^ New name
        -> Instance
setName t s = t { name = s }

-- * Update functions

-- | Changes the primary node of the instance.
setPri :: Instance  -- ^ the original instance
        -> T.Ndx    -- ^ the new primary node
        -> Instance -- ^ the modified instance
setPri t p = t { pnode = p }

-- | Changes the secondary node of the instance.
setSec :: Instance  -- ^ the original instance
        -> T.Ndx    -- ^ the new secondary node
        -> Instance -- ^ the modified instance
setSec t s = t { snode = s }

-- | Changes both nodes of the instance.
setBoth :: Instance  -- ^ the original instance
         -> T.Ndx    -- ^ new primary node index
         -> T.Ndx    -- ^ new secondary node index
         -> Instance -- ^ the modified instance
setBoth t p s = t { pnode = p, snode = s }
