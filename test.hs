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

import Data.IORef
import Test.QuickCheck.Batch
import System.IO
import System.Exit
import System (getArgs)

import Ganeti.HTools.QC

fast :: TestOptions
fast = TestOptions
              { no_of_tests         = 500
              , length_of_tests     = 10
              , debug_tests         = False }

slow :: TestOptions
slow = TestOptions
              { no_of_tests         = 50
              , length_of_tests     = 100
              , debug_tests         = False }

incIORef :: IORef Int -> IO ()
incIORef ir = atomicModifyIORef ir (\x -> (x + 1, ()))

-- | Wrapper over a test runner with error counting
wrapTest :: IORef Int
         -> (TestOptions -> IO TestResult)
         -> TestOptions -> IO TestResult
wrapTest ir t to = do
    tr <- t to
    case tr of
      TestFailed _ _ -> incIORef ir
      TestAborted e -> do
        incIORef ir
        putStrLn ("Failure during test: <" ++ show e ++ ">")
      _ -> return ()
    return tr

allTests :: [(String, TestOptions, [TestOptions -> IO TestResult])]
allTests =
  [ ("Utils", fast, testUtils)
  , ("PeerMap", fast, testPeerMap)
  , ("Container", fast, testContainer)
  , ("Instance", fast, testInstance)
  , ("Node", fast, testNode)
  , ("Text", fast, testText)
  , ("OpCodes", fast, testOpCodes)
  , ("Jobs", fast, testJobs)
  , ("Loader", fast, testLoader)
  , ("Cluster", slow, testCluster)
  ]

main :: IO ()
main = do
  errs <- newIORef 0
  let wrap = map (wrapTest errs)
  args <- getArgs
  let tests = if null args
              then allTests
              else filter (\(name, _, _) -> name `elem` args) allTests
  mapM_ (\(name, opts, tl) -> runTests name opts (wrap tl)) tests
  terr <- readIORef errs
  (if terr > 0
   then do
     hPutStrLn stderr $ "A total of " ++ show terr ++ " tests failed."
     exitWith $ ExitFailure 1
   else putStrLn "All tests succeeded.")
