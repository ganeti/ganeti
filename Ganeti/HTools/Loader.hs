{-| Loading data from external sources

This module holds the common code for loading the cluster state from external sources.

-}

module Ganeti.HTools.Loader
    where

type NameAssoc = [(String, Int)]

-- | Lookups a node into an assoc list
lookupNode :: (Monad m) => NameAssoc -> String -> String -> m Int
lookupNode ktn inst node =
    case lookup node ktn of
      Nothing -> fail $ "Unknown node '" ++ node ++ "' for instance " ++ inst
      Just idx -> return idx

assignIndices :: (a -> Int -> a)
              -> [(String, a)]
              -> (NameAssoc, [(Int, a)])
assignIndices set_fn =
    unzip . map (\ (idx, (k, v)) -> ((k, idx), (idx, set_fn v idx)))
          . zip [0..]
