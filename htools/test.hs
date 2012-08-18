{-| Unittest runner for ganeti-htools.

-}

{-

Copyright (C) 2009, 2011, 2012 Google Inc.

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

import Data.Char
import Data.IORef
import Data.List
import Data.Maybe (fromMaybe)
import System.Console.GetOpt ()
import System.Environment (getArgs)
import System.Exit
import System.IO
import Test.QuickCheck
import Text.Printf

import Ganeti.HTools.QC
import Ganeti.HTools.CLI
import Ganeti.HTools.Utils (sepSplit)

-- | Options list and functions.
options :: [OptType]
options =
  [ oReplay
  , oVerbose
  , oShowVer
  , oShowHelp
  , oTestCount
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

-- | Wrapper over a test runner with error counting.
wrapTest :: IORef Int
         -> (Args -> IO Result, String)
         -> Args
         -> IO (Result, Char, String)
wrapTest ir (test, desc) opts = do
  r <- test opts
  c <- case r of
         Success {} -> return '.'
         GaveUp  {} -> return '?'
         Failure {} -> incIORef ir >> return '#'
         NoExpectedFailure {} -> incIORef ir >> return '*'
  return (r, c, desc)

runTests :: String
         -> Args
         -> [Args -> IO (Result, Char, String)]
         -> Int
         -> IO [(Result, String)]

runTests name opts tests max_count = do
  _ <- printf "%25s : " name
  hFlush stdout
  results <- mapM (\t -> do
                     (r, c, desc) <- t opts
                     putChar c
                     hFlush stdout
                     return (r, desc)
                  ) tests
  let alldone = sum . map (numTests . fst) $ results
  _ <- printf "%*s(%d)\n" (max_count - length tests + 1) " " alldone
  mapM_ (\(r, desc) ->
             case r of
               Failure { output = o, usedSeed = u, usedSize = size } ->
                   printf "Test %s failed (seed was %s, test size %d): %s\n"
                          desc (show u) size o
               GaveUp { numTests = passed } ->
                   printf "Test %s incomplete: gave up with only %d\
                          \ passes after discarding %d tests\n"
                          desc passed (maxDiscard opts)
               _ -> return ()
        ) results
  return results

allTests :: [(Args, (String, [(Args -> IO Result, String)]))]
allTests =
  [ (fast, testUtils)
  , (fast, testPeerMap)
  , (fast, testContainer)
  , (fast, testInstance)
  , (fast, testNode)
  , (fast, testText)
  , (fast, testSimu)
  , (fast, testOpCodes)
  , (fast, testJobs)
  , (fast, testLoader)
  , (fast, testTypes)
  , (fast, testCLI)
  , (fast, testJSON)
  , (fast, testLUXI)
  , (fast, testSsconf)
  , (fast, testQuery2)
  , (slow, testCluster)
  , (fast, testRpc)
  ]

-- | Extracts the name of a test group.
extractName :: (Args, (String, [(Args -> IO Result, String)])) -> String
extractName (_, (name, _)) = name

-- | Lowercase a string.
lower :: String -> String
lower = map toLower

transformTestOpts :: Args -> Options -> IO Args
transformTestOpts args opts = do
  r <- case optReplay opts of
         Nothing -> return Nothing
         Just str -> do
           let vs = sepSplit ',' str
           case vs of
             [rng, size] -> return $ Just (read rng, read size)
             _ -> fail "Invalid state given"
  return args { chatty = optVerbose opts > 1
              , replay = r
              , maxSuccess = fromMaybe (maxSuccess args) (optTestCount opts)
              , maxDiscard = fromMaybe (maxDiscard args) (optTestCount opts)
              }

main :: IO ()
main = do
  errs <- newIORef 0
  let wrap = map (wrapTest errs)
  cmd_args <- getArgs
  (opts, args) <- parseOpts cmd_args "test" options
  tests <- if null args
             then return allTests
             else let args' = map lower args
                      selected = filter ((`elem` args') . lower .
                                         extractName) allTests
                  in if null selected
                       then do
                         hPutStrLn stderr $ "No tests matching '"
                            ++ unwords args ++ "', available tests: "
                            ++ intercalate ", " (map extractName allTests)
                         exitWith $ ExitFailure 1
                       else return selected

  let max_count = maximum $ map (\(_, (_, t)) -> length t) tests
  mapM_ (\(targs, (name, tl)) ->
           transformTestOpts targs opts >>= \newargs ->
           runTests name newargs (wrap tl) max_count) tests
  terr <- readIORef errs
  if terr > 0
    then do
      hPutStrLn stderr $ "A total of " ++ show terr ++ " tests failed."
      exitWith $ ExitFailure 1
    else putStrLn "All tests succeeded."
