{-| Solver for N+1 cluster errors

-}

module Main (main) where

import Data.List
import Data.Function
import Data.Maybe (isJust, fromJust)
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Types

-- | Command line options structure.
data Options = Options
    { optShowVer   :: Bool           -- ^ Just show the program version
    , optShowHelp  :: Bool           -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowVer   = False
 , optShowHelp  = False
 }

instance CLI.CLIOptions Options where
    showVersion = optShowVer
    showHelp    = optShowHelp

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

-- | Compute online nodes from a Node.List
getOnline :: Node.List -> [Node.Node]
getOnline = filter (not . Node.offline) . Container.elems

-- | Try to allocate an instance on the cluster
tryAlloc :: (Monad m) =>
            Node.List
         -> Instance.List
         -> Instance.Instance
         -> Int
         -> m [(Maybe Node.List, [Node.Node])]
tryAlloc nl _ inst 2 =
    let all_nodes = getOnline nl
        all_pairs = liftM2 (,) all_nodes all_nodes
        ok_pairs = filter (\(x, y) -> Node.idx x /= Node.idx y) all_pairs
        sols = map (\(p, s) ->
                        (fst $ Cluster.allocateOnPair nl inst p s, [p, s]))
               ok_pairs
    in return sols

tryAlloc nl _ inst 1 =
    let all_nodes = getOnline nl
        sols = map (\p -> (fst $ Cluster.allocateOnSingle nl inst p, [p]))
               all_nodes
    in return sols

tryAlloc _ _ _ reqn = fail $ "Unsupported number of alllocation \
                             \destinations required (" ++ (show reqn) ++
                                               "), only two supported"

-- | Try to allocate an instance on the cluster
tryReloc :: (Monad m) =>
            Node.List
         -> Instance.List
         -> Idx
         -> Int
         -> [Ndx]
         -> m [(Maybe Node.List, [Node.Node])]
tryReloc nl il xid 1 ex_idx =
    let all_nodes = getOnline nl
        inst = Container.find xid il
        ex_idx' = (Instance.pnode inst):ex_idx
        valid_nodes = filter (not . flip elem ex_idx' . Node.idx) all_nodes
        valid_idxes = map Node.idx valid_nodes
        sols1 = map (\x -> let (mnl, _, _, _) =
                                    Cluster.applyMove nl inst
                                               (Cluster.ReplaceSecondary x)
                            in (mnl, [Container.find x nl])
                     ) valid_idxes
    in return sols1

tryReloc _ _ _ reqn _  = fail $ "Unsupported number of relocation \
                                \destinations required (" ++ (show reqn) ++
                                                  "), only one supported"

filterFails :: (Monad m) => [(Maybe Node.List, [Node.Node])]
            -> m [(Node.List, [Node.Node])]
filterFails sols =
    if null sols then fail "No nodes onto which to allocate at all"
    else let sols' = filter (isJust . fst) sols
         in if null sols' then
                fail "No valid allocation solutions"
            else
                return $ map (\(x, y) -> (fromJust x, y)) sols'

processResults :: (Monad m) => [(Node.List, [Node.Node])]
               -> m (String, [Node.Node])
processResults sols =
    let sols' = map (\(nl', ns) -> (Cluster.compCV  nl', ns)) sols
        sols'' = sortBy (compare `on` fst) sols'
        (best, w) = head sols''
        (worst, l) = last sols''
        info = printf "Valid results: %d, best score: %.8f for node(s) %s, \
                      \worst score: %.8f for node(s) %s" (length sols'')
                      best (intercalate "/" . map Node.name $ w)
                      worst (intercalate "/" . map Node.name $ l)
    in return (info, w)

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (_, args) <- CLI.parseOpts cmd_args "hail" options defaultOptions

  when (null args) $ do
         hPutStrLn stderr "Error: this program needs an input file."
         exitWith $ ExitFailure 1

  let input_file = head args
  input_data <- readFile input_file

  request <- case (parseData input_data) of
               Bad err -> do
                 putStrLn $ "Error: " ++ err
                 exitWith $ ExitFailure 1
               Ok rq -> return rq

  let Request rqtype nl il csf = request
      new_nodes = case rqtype of
                    Allocate xi reqn -> tryAlloc nl il xi reqn
                    Relocate idx reqn exnodes ->
                        tryReloc nl il idx reqn exnodes
  let sols = new_nodes >>= filterFails >>= processResults
  let (ok, info, rn) = case sols of
               Ok (info, sn) -> (True, "Request successful: " ++ info,
                                     map ((++ csf) . Node.name) sn)
               Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rn
  putStrLn resp
