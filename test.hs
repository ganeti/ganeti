{-| Unittest runner for ganeti-htools

-}

{-

Copyright (C) 2009 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

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
  runTests "Text" options test_Text
