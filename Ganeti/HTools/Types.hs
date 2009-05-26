{-| Some common types.

-}

module Ganeti.HTools.Types
    where

-- | The type used to hold idx-to-name mappings
type NameList = [(Int, String)]

-- | The type used to hold name-to-idx mappings
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

-- | A generic class for items that have names and indices
class Element a where
    nameOf  :: a -> String
    idxOf   :: a -> Int
    setName :: a -> String -> a
    setIdx  :: a -> Int -> a
