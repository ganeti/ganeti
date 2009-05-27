{-| Unittest runner for htools

-}

module Main(main) where

import Test.QuickCheck.Batch
import Ganeti.HTools.QC

options = TestOptions
      { no_of_tests         = 500
      , length_of_tests     = 5
      , debug_tests         = False }

main = do
  runTests "PeerMap" options
       [ run prop_PeerMap_addIdempotent
       , run prop_PeerMap_removeIdempotent
       , run prop_PeerMap_maxElem
       , run prop_PeerMap_addFind
       , run prop_PeerMap_findMissing
       ]

  runTests "Node" options
       [ run prop_Node_addPri
       , run prop_Node_addSec
       ]
