{-| Unittest runner for ganeti-htools

-}

{-

Copyright (C) 2009, 2011 Google Inc.

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
import Test.QuickCheck
import System.Console.GetOpt
import System.IO
import System.Exit
import System (getArgs)
import Text.Printf

import Ganeti.HTools.QC
import Ganeti.HTools.CLI
import Ganeti.HTools.Utils (sepSplit)

-- | Options list and functions
options :: [OptType]
options =
    [ oReplay
    , oVerbose
    , oShowVer
    , oShowHelp
    ]

fast :: Args
fast = stdArgs
       { maxSuccess = 500
       , chatty     = False
       }

slow :: Args
slow = stdArgs
       { maxSuccess = 50
       , chatty     = False
       }

incIORef :: IORef Int -> IO ()
incIORef ir = atomicModifyIORef ir (\x -> (x + 1, ()))

-- | Wrapper over a test runner with error counting
wrapTest :: IORef Int
         -> (Args -> IO Result)
         -> Args
         -> IO (Result, Char)
wrapTest ir test opts = do
  r <- test opts
  c <- case r of
         Success {} -> return '.'
         GaveUp  {} -> return '?'
         Failure {} -> incIORef ir >> return '#'
         NoExpectedFailure {} -> incIORef ir >> return '*'
  return (r, c)

runTests name opts tests max_count = do
  _ <- printf "%25s : " name
  hFlush stdout
  results <- mapM (\t -> do
                     (r, c) <- t opts
                     putChar c
                     hFlush stdout
                     return r
                  ) tests
  let alldone = sum . map numTests $ results
  _ <- printf "%*s(%d)\n" (max_count - length tests + 1) " " alldone
  mapM_ (\(idx, r) ->
             case r of
               Failure { output = o, usedSeed = u, usedSize = size } ->
                   printf "Test %d failed (seed was %s, test size %d): %s\n"
                          idx (show u) size o
               GaveUp { numTests = passed } ->
                   printf "Test %d incomplete: gave up with only %d\
                          \ passes after discarding %d tests\n"
                          idx passed (maxDiscard opts)
               _ -> return ()
        ) $ zip ([1..]::[Int]) results
  return results

allTests :: [(String, Args, [Args -> IO Result])]
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

transformTestOpts :: Args -> Options -> IO Args
transformTestOpts args opts = do
  r <- case optReplay opts of
         Nothing -> return Nothing
         Just str -> do
           let vs = sepSplit ',' str
           (case vs of
              [rng, size] -> return $ Just (read rng, read size)
              _ -> fail "Invalid state given")
  return args { chatty = optVerbose opts > 1,
                replay = r
              }

main :: IO ()
main = do
  errs <- newIORef 0
  let wrap = map (wrapTest errs)
  cmd_args <- System.getArgs
  (opts, args) <- parseOpts cmd_args "test" options
  let tests = if null args
              then allTests
              else filter (\(name, _, _) -> name `elem` args) allTests
      max_count = maximum $ map (\(_, _, t) -> length t) tests
  mapM_ (\(name, targs, tl) ->
             transformTestOpts targs opts >>= \newargs ->
             runTests name newargs (wrap tl) max_count) tests
  terr <- readIORef errs
  (if terr > 0
   then do
     hPutStrLn stderr $ "A total of " ++ show terr ++ " tests failed."
     exitWith $ ExitFailure 1
   else putStrLn "All tests succeeded.")
