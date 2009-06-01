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
  runTests "PeerMap" options test_PeerMap
  runTests "Container" options test_Container
  runTests "Instance" options test_Instance
  runTests "Node" options test_Node
