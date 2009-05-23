{-| Some common types.

-}

module Ganeti.HTools.Types
    where

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node

type NodeList = Container.Container Node.Node
type InstanceList = Container.Container Instance.Instance

-- | The type used to hold idx-to-name mappings
type NameList = [(Int, String)]

-- | The type used to hold name-to-idx mappings
type NameAssoc = [(String, Int)]

type IdxNode = [(Int, Node.Node)]
type IdxInstance = [(Int, Instance.Instance)]

{-

This is similar to the JSON library Result type - *very* similar, but
we want to use it in multiple places, so we abstract it into a
mini-library here

-}

data Result a
    = Bad String
    | Ok a
    deriving (Show)

instance Monad Result where
    (>>=) (Bad x) _ = Bad x
    (>>=) (Ok x) fn = fn x
    return = Ok
    fail = Bad

-- | A generic class for nodes and instances
class Element a where
    name    :: a -> String
    idx     :: a -> Int
    setName :: a -> String -> a
    setIdx  :: a -> Int -> a

-- Let's make nodes elements of the cluster
instance Element Node.Node where
    name = Node.name
    idx = Node.idx
    setName = Node.setName
    setIdx = Node.setIdx

-- And instances too
instance Element Instance.Instance where
    name = Instance.name
    idx = Instance.idx
    setName = Instance.setName
    setIdx = Instance.setIdx

-- | Compute the name of an element in a container
cNameOf :: (Element a) => Container.Container a -> Container.Key -> String
cNameOf c k = name $ Container.find k c

-- | Compute the maximum name length in an Element Container
cMaxNamelen :: (Element a) => Container.Container a -> Int
cMaxNamelen = maximum . map (length . name) . Container.elems
