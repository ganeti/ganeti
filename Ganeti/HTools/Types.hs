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
