{-| Module describing an instance.

The instance data type holds very few fields, the algorithm
intelligence is in the "Node" and "Cluster" modules.

-}
module Ganeti.HTools.Instance where

data Instance = Instance { mem :: Int   -- ^ memory of the instance
                         , dsk :: Int   -- ^ disk size of instance
                         , pnode :: Int -- ^ original primary node
                         , snode :: Int -- ^ original secondary node
                         , idx :: Int   -- ^ internal index for book-keeping
                         } deriving (Show)

create :: String -> String -> Int -> Int -> Instance
create mem_init dsk_init pn sn = Instance {
                              mem = read mem_init,
                              dsk = read dsk_init,
                              pnode = pn,
                              snode = sn,
                              idx = -1
                            }

-- | Changes the primary node of the instance.
setPri :: Instance  -- ^ the original instance
        -> Int      -- ^ the new primary node
        -> Instance -- ^ the modified instance
setPri t p = t { pnode = p }

-- | Changes the secondary node of the instance.
setSec :: Instance  -- ^ the original instance
        -> Int      -- ^ the new secondary node
        -> Instance -- ^ the modified instance
setSec t s = t { snode = s }

-- | Changes both nodes of the instance.
setBoth :: Instance  -- ^ the original instance
         -> Int      -- ^ new primary node index
         -> Int      -- ^ new secondary node index
         -> Instance -- ^ the modified instance
setBoth t p s = t { pnode = p, snode = s }

-- | Changes the index.
-- This is used only during the building of the data structures.
setIdx :: Instance  -- ^ the original instance
        -> Int      -- ^ new index
        -> Instance -- ^ the modified instance
setIdx t i = t { idx = i }
