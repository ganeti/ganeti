{-| Base common functionality.

This module holds common functionality shared across Ganeti daemons,
HTools and any other programs.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Ganeti.Common
  ( GenericOptType
  , StandardOptions(..)
  , OptCompletion(..)
  , ArgCompletion(..)
  , PersonalityList
  , optComplYesNo
  , oShowHelp
  , oShowVer
  , oShowComp
  , usageHelp
  , versionInfo
  , formatCommands
  , reqWithConversion
  , parseYesNo
  , parseOpts
  , parseOptsInner
  , parseOptsCmds
  , genericMainCmds
  , fillUpList
  , fillPairFromMaybe
  , pickPairUnique
  ) where

import Control.Monad (foldM)
import Data.Char (toLower)
import Data.List (intercalate, stripPrefix, sortBy)
import Data.Maybe (fromMaybe)
import Data.Ord (comparing)
import qualified Data.Version
import System.Console.GetOpt
import System.Environment
import System.Exit
import System.Info
import System.IO
import Text.Printf (printf)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Utils (wrap)
import qualified Ganeti.Version as Version (version)

-- | Parameter type.
data OptCompletion = OptComplNone             -- ^ No parameter to this option
                   | OptComplFile             -- ^ An existing file
                   | OptComplDir              -- ^ An existing directory
                   | OptComplHost             -- ^ Host name
                   | OptComplInetAddr         -- ^ One ipv4\/ipv6 address
                   | OptComplOneNode          -- ^ One node
                   | OptComplManyNodes        -- ^ Many nodes, comma-sep
                   | OptComplOneInstance      -- ^ One instance
                   | OptComplManyInstances    -- ^ Many instances, comma-sep
                   | OptComplOneOs            -- ^ One OS name
                   | OptComplOneIallocator    -- ^ One iallocator
                   | OptComplInstAddNodes     -- ^ Either one or two nodes
                   | OptComplOneGroup         -- ^ One group
                   | OptComplInteger          -- ^ Integer values
                   | OptComplFloat            -- ^ Float values
                   | OptComplJobId            -- ^ Job Id
                   | OptComplCommand          -- ^ Command (executable)
                   | OptComplString           -- ^ Arbitrary string
                   | OptComplChoices [String] -- ^ List of string choices
                   | OptComplSuggest [String] -- ^ Suggested choices
                   deriving (Show, Eq)

-- | Argument type. This differs from (and wraps) an Option by the
-- fact that it can (and usually does) support multiple repetitions of
-- the same argument, via a min and max limit.
data ArgCompletion = ArgCompletion OptCompletion Int (Maybe Int)
                     deriving (Show, Eq)

-- | A personality definition.
type Personality a = ( a -> [String] -> IO () -- The main function
                     , IO [GenericOptType a]  -- The options
                     , [ArgCompletion]        -- The description of args
                     , String                 -- Description
                     )

-- | Personality lists type, common across all binaries that expose
-- multiple personalities.
type PersonalityList  a = [(String, Personality a)]

-- | Yes\/no choices completion.
optComplYesNo :: OptCompletion
optComplYesNo = OptComplChoices ["yes", "no"]

-- | Text serialisation for 'OptCompletion', used on the Python side.
complToText :: OptCompletion -> String
complToText (OptComplChoices choices) = "choices=" ++ intercalate "," choices
complToText (OptComplSuggest choices) = "suggest=" ++ intercalate "," choices
complToText compl =
  let show_compl = show compl
      stripped = stripPrefix "OptCompl" show_compl
  in map toLower $ fromMaybe show_compl stripped

-- | Text serialisation for 'ArgCompletion'.
argComplToText :: ArgCompletion -> String
argComplToText (ArgCompletion optc min_cnt max_cnt) =
  complToText optc ++ " " ++ show min_cnt ++ " " ++ maybe "none" show max_cnt

-- | Abbreviation for the option type.
type GenericOptType a = (OptDescr (a -> Result a), OptCompletion)

-- | Type class for options which support help and version.
class StandardOptions a where
  helpRequested :: a -> Bool
  verRequested  :: a -> Bool
  compRequested :: a -> Bool
  requestHelp   :: a -> a
  requestVer    :: a -> a
  requestComp   :: a -> a

-- | Option to request help output.
oShowHelp :: (StandardOptions a) => GenericOptType a
oShowHelp = (Option "h" ["help"] (NoArg (Ok . requestHelp)) "show help",
             OptComplNone)

-- | Option to request version information.
oShowVer :: (StandardOptions a) => GenericOptType a
oShowVer = (Option "V" ["version"] (NoArg (Ok . requestVer))
            "show the version of the program",
            OptComplNone)

-- | Option to request completion information
oShowComp :: (StandardOptions a) => GenericOptType a
oShowComp =
  (Option "" ["help-completion"] (NoArg (Ok . requestComp) )
   "show completion info", OptComplNone)

-- | Usage info.
usageHelp :: String -> [GenericOptType a] -> String
usageHelp progname =
  usageInfo (printf "%s %s\nUsage: %s [OPTION...]"
             progname Version.version progname) . map fst

-- | Show the program version info.
versionInfo :: String -> String
versionInfo progname =
  printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
         progname Version.version compilerName
         (Data.Version.showVersion compilerVersion)
         os arch

-- | Show completion info.
completionInfo :: String -> [GenericOptType a] -> [ArgCompletion] -> String
completionInfo _ opts args =
  unlines $
  map (\(Option shorts longs _ _, compinfo) ->
         let all_opts = map (\c -> ['-', c]) shorts ++ map ("--" ++) longs
         in intercalate "," all_opts ++ " " ++ complToText compinfo
      ) opts ++
  map argComplToText args

-- | Helper for parsing a yes\/no command line flag.
parseYesNo :: Bool         -- ^ Default value (when we get a @Nothing@)
           -> Maybe String -- ^ Parameter value
           -> Result Bool  -- ^ Resulting boolean value
parseYesNo v Nothing      = return v
parseYesNo _ (Just "yes") = return True
parseYesNo _ (Just "no")  = return False
parseYesNo _ (Just s)     = fail ("Invalid choice '" ++ s ++
                                  "', pass one of 'yes' or 'no'")

-- | Helper function for required arguments which need to be converted
-- as opposed to stored just as string.
reqWithConversion :: (String -> Result a)
                  -> (a -> b -> Result b)
                  -> String
                  -> ArgDescr (b -> Result b)
reqWithConversion conversion_fn updater_fn =
  ReqArg (\string_opt opts -> do
            parsed_value <- conversion_fn string_opt
            updater_fn parsed_value opts)

-- | Max command length when formatting command list output.
maxCmdLen :: Int
maxCmdLen = 60

-- | Formats the description of various commands.
formatCommands :: (StandardOptions a) => PersonalityList a -> [String]
formatCommands personalities =
  concatMap (\(cmd, (_, _, _, desc)) ->
              fmtDesc cmd (wrap maxWidth desc) "-" []) $
  sortBy (comparing fst) personalities
    where mlen = min maxCmdLen . maximum $ map (length . fst) personalities
          maxWidth = 79 - 3 - mlen
          fmtDesc _ [] _ acc = reverse acc
          fmtDesc cmd (d : ds) sep acc =
            fmtDesc "" ds " " (printf " %-*s %s %s" mlen cmd sep d : acc)

-- | Formats usage for a multi-personality program.
formatCmdUsage :: (StandardOptions a) => String -> PersonalityList a -> String
formatCmdUsage prog personalities =
  let header = [ printf "Usage: %s {command} [options...] [argument...]" prog
               , printf "%s <command> --help to see details, or man %s"
                   prog prog
               , ""
               , "Commands:"
               ]
      rows = formatCommands personalities
  in unlines $ header ++ rows

-- | Displays usage for a program and exits.
showCmdUsage :: (StandardOptions a) =>
                String            -- ^ Program name
             -> PersonalityList a -- ^ Personality list
             -> Bool              -- ^ Whether the exit code is success or not
             -> IO b
showCmdUsage prog personalities success = do
  let usage = formatCmdUsage prog personalities
  putStr usage
  if success
    then exitSuccess
    else exitWith $ ExitFailure C.exitFailure

-- | Generates completion information for a multi-command binary.
multiCmdCompletion :: (StandardOptions a) => PersonalityList a -> String
multiCmdCompletion personalities =
  argComplToText $
    ArgCompletion (OptComplChoices (map fst personalities))
      1 (Just 1)

-- | Displays completion information for a multi-command binary and exits.
showCmdCompletion :: (StandardOptions a) => PersonalityList a -> IO b
showCmdCompletion personalities =
  putStrLn (multiCmdCompletion personalities) >> exitSuccess

-- | Command line parser, using a generic 'Options' structure.
parseOpts :: (StandardOptions a) =>
             a                      -- ^ The default options
          -> [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [GenericOptType a]     -- ^ The supported command line options
          -> [ArgCompletion]        -- ^ The supported command line arguments
          -> IO (a, [String])       -- ^ The resulting options and
                                    -- leftover arguments
parseOpts defaults argv progname options arguments =
  case parseOptsInner defaults argv progname options arguments of
    Left (code, msg) -> do
      hPutStr (if code == ExitSuccess then stdout else stderr) msg
      exitWith code
    Right result ->
      return result

-- | Command line parser, for programs with sub-commands.
parseOptsCmds :: (StandardOptions a) =>
                 a                      -- ^ The default options
              -> [String]               -- ^ The command line arguments
              -> String                 -- ^ The program name
              -> PersonalityList a      -- ^ The supported commands
              -> [GenericOptType a]     -- ^ Generic options
              -> IO (a, [String], a -> [String] -> IO ())
                     -- ^ The resulting options and leftover arguments
parseOptsCmds defaults argv progname personalities genopts = do
  let usage = showCmdUsage progname personalities
      check c = case c of
                  -- hardcoded option strings here!
                  "--version" -> putStrLn (versionInfo progname) >> exitSuccess
                  "--help"    -> usage True
                  "--help-completion" -> showCmdCompletion personalities
                  _           -> return c
  (cmd, cmd_args) <- case argv of
                       cmd:cmd_args -> do
                         cmd' <- check cmd
                         return (cmd', cmd_args)
                       [] -> usage False
  case cmd `lookup` personalities of
    Nothing -> usage False
    Just (mainfn, optdefs, argdefs, _) -> do
      optdefs' <- optdefs
      (opts, args) <- parseOpts defaults cmd_args progname
                      (optdefs' ++ genopts) argdefs
      return (opts, args, mainfn)

-- | Inner parse options. The arguments are similar to 'parseOpts',
-- but it returns either a 'Left' composed of exit code and message,
-- or a 'Right' for the success case.
parseOptsInner :: (StandardOptions a) =>
                  a
               -> [String]
               -> String
               -> [GenericOptType a]
               -> [ArgCompletion]
               -> Either (ExitCode, String) (a, [String])
parseOptsInner defaults argv progname options arguments  =
  case getOpt Permute (map fst options) argv of
    (opts, args, []) ->
      case foldM (flip id) defaults opts of
           Bad msg -> Left (ExitFailure 1,
                            "Error while parsing command line arguments:\n"
                            ++ msg ++ "\n")
           Ok parsed ->
             select (Right (parsed, args))
                 [ (helpRequested parsed,
                    Left (ExitSuccess, usageHelp progname options))
                 , (verRequested parsed,
                    Left (ExitSuccess, versionInfo progname))
                 , (compRequested parsed,
                    Left (ExitSuccess, completionInfo progname options
                                         arguments))
                 ]
    (_, _, errs) ->
      Left (ExitFailure 2, "Command line error: "  ++ concat errs ++ "\n" ++
            usageHelp progname options)

-- | Parse command line options and execute the main function of a
-- multi-personality binary.
genericMainCmds :: (StandardOptions a) =>
                   a
                -> PersonalityList a
                -> [GenericOptType a]
                -> IO ()
genericMainCmds defaults personalities genopts = do
  cmd_args <- getArgs
  prog <- getProgName
  (opts, args, fn) <-
    parseOptsCmds defaults cmd_args prog personalities genopts
  fn opts args

-- | Order a list of pairs in the order of the given list and fill up
-- the list for elements that don't have a matching pair
fillUpList :: ([(a, b)] -> a -> (a, b)) -> [a] -> [(a, b)] -> [(a, b)]
fillUpList fill_fn inputs pairs =
  map (fill_fn pairs) inputs

-- | Fill up a pair with fillup element if no matching pair is present
fillPairFromMaybe :: (a -> (a, b)) -> (a -> [(a, b)] -> Maybe (a, b))
                  -> [(a, b)] -> a -> (a, b)
fillPairFromMaybe fill_fn pick_fn pairs element = fromMaybe (fill_fn element)
    (pick_fn element pairs)

-- | Check if the given element matches the given pair
isMatchingPair :: (Eq a) => a -> (a, b) -> Bool
isMatchingPair element (pair_element, _) = element == pair_element

-- | Pick a specific element's pair from the list
pickPairUnique :: (Eq a) => a -> [(a, b)] -> Maybe (a, b)
pickPairUnique element pairs =
  let res = filter (isMatchingPair element) pairs
  in case res of
    [x] -> Just x
    -- if we have more than one result, we should get suspcious
    _ -> Nothing
