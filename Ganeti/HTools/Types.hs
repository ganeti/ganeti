{-| Some common types.

-}

module Ganeti.HTools.Types
    ( Idx
    , Ndx
    , NameAssoc
    , Result(..)
    , Element(..)
    ) where

-- | The instance index type.
type Idx = Int

-- | The node index type.
type Ndx = Int

-- | The type used to hold name-to-idx mappings.
type NameAssoc = [(String, Int)]

{-|

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

-- | A generic class for items that have updateable names and indices.
class Element a where
    -- | Returns the name of the element
    nameOf  :: a -> String
    -- | Returns the index of the element
    idxOf   :: a -> Int
    -- | Updates the name of the element
    setName :: a -> String -> a
    -- | Updates the index of the element
    setIdx  :: a -> Int -> a
