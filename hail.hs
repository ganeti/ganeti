{-| Solver for N+1 cluster errors

-}

module Main (main) where

import Data.List
import Data.Function
import Data.Maybe (isJust, fromJust, fromMaybe)
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
    { optShowNodes :: Bool           -- ^ Whether to show node status
    , optShowCmds  :: Maybe FilePath -- ^ Whether to show the command list
    , optOneline   :: Bool           -- ^ Switch output to a single line
    , optNodef     :: FilePath       -- ^ Path to the nodes file
    , optNodeSet   :: Bool           -- ^ The nodes have been set by options
    , optInstf     :: FilePath       -- ^ Path to the instances file
    , optInstSet   :: Bool           -- ^ The insts have been set by options
    , optMaxLength :: Int            -- ^ Stop after this many steps
    , optMaster    :: String         -- ^ Collect data from RAPI
    , optVerbose   :: Int            -- ^ Verbosity level
    , optOffline   :: [String]       -- ^ Names of offline nodes
    , optMinScore  :: Cluster.Score  -- ^ The minimum score we aim for
    , optShowVer   :: Bool           -- ^ Just show the program version
    , optShowHelp  :: Bool           -- ^ Just show the help
    } deriving Show

instance CLI.CLIOptions Options where
    showVersion = optShowVer
    showHelp    = optShowHelp

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optShowCmds  = Nothing
 , optOneline   = False
 , optNodef     = "nodes"
 , optNodeSet   = False
 , optInstf     = "instances"
 , optInstSet   = False
 , optMaxLength = -1
 , optMaster    = ""
 , optVerbose   = 1
 , optOffline   = []
 , optMinScore  = 1e-9
 , optShowVer   = False
 , optShowHelp  = False
 }

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['C']     ["print-commands"]
      (OptArg ((\ f opts -> opts { optShowCmds = Just f }) . fromMaybe "-")
                  "FILE")
      "print the ganeti command list for reaching the solution,\
      \if an argument is passed then write the commands to a file named\
      \ as such"
    , Option ['o']     ["oneline"]
      (NoArg (\ opts -> opts { optOneline = True }))
      "print the ganeti command list for reaching the solution"
    , Option ['n']     ["nodes"]
      (ReqArg (\ f opts -> opts { optNodef = f, optNodeSet = True }) "FILE")
      "the node list FILE"
    , Option ['i']     ["instances"]
      (ReqArg (\ f opts -> opts { optInstf =  f, optInstSet = True }) "FILE")
      "the instance list FILE"
    , Option ['m']     ["master"]
      (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
      "collect data via RAPI at the given ADDRESS"
    , Option ['l']     ["max-length"]
      (ReqArg (\ i opts -> opts { optMaxLength =  (read i)::Int }) "N")
      "cap the solution at this many moves (useful for very unbalanced \
      \clusters)"
    , Option ['v']     ["verbose"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) + 1 }))
      "increase the verbosity level"
    , Option ['q']     ["quiet"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) - 1 }))
      "decrease the verbosity level"
    , Option ['O']     ["offline"]
      (ReqArg (\ n opts -> opts { optOffline = n:optOffline opts }) "NODE")
      " set node as offline"
    , Option ['e']     ["min-score"]
      (ReqArg (\ e opts -> opts { optMinScore = read e }) "EPSILON")
      " mininum score to aim for"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

-- | Try to allocate an instance on the cluster
tryAlloc :: (Monad m) =>
            NodeList
         -> InstanceList
         -> Instance.Instance
         -> Int
         -> m [(Maybe NodeList, [Node.Node])]
tryAlloc nl _ inst 2 =
    let all_nodes = Container.elems nl
        all_pairs = liftM2 (,) all_nodes all_nodes
        ok_pairs = filter (\(x, y) -> Node.idx x /= Node.idx y) all_pairs
        sols = map (\(p, s) ->
                        (fst $ Cluster.allocateOnPair nl inst p s, [p, s]))
               ok_pairs
    in return sols

tryAlloc nl _ inst 1 =
    let all_nodes = Container.elems nl
        sols = map (\p -> (fst $ Cluster.allocateOnSingle nl inst p, [p]))
               all_nodes
    in return sols

tryAlloc _ _ _ reqn = fail $ "Unsupported number of alllocation \
                             \destinations required (" ++ (show reqn) ++
                                               "), only two supported"

-- | Try to allocate an instance on the cluster
tryReloc :: (Monad m) =>
            NodeList
         -> InstanceList
         -> Int
         -> Int
         -> [Int]
         -> m [(Maybe NodeList, [Node.Node])]
tryReloc nl il xid 1 ex_idx =
    let all_nodes = Container.elems nl
        inst = Container.find xid il
        valid_nodes = filter (not . flip elem ex_idx . idx) all_nodes
        valid_idxes = map Node.idx valid_nodes
        nl' = Container.map (\n -> if elem (Node.idx n) ex_idx then
                                       Node.setOffline n True
                                   else n) nl
        sols1 = map (\x -> let (mnl, _, _, _) =
                                    Cluster.applyMove nl' inst
                                               (Cluster.ReplaceSecondary x)
                            in (mnl, [Container.find x nl'])
                     ) valid_idxes
    in return sols1

tryReloc _ _ _ reqn _  = fail $ "Unsupported number of relocation \
                                \destinations required (" ++ (show reqn) ++
                                                  "), only one supported"

filterFails :: (Monad m) => [(Maybe NodeList, [Node.Node])]
            -> m [(NodeList, [Node.Node])]
filterFails sols =
    if null sols then fail "No nodes onto which to allocate at all"
    else let sols' = filter (isJust . fst) sols
         in if null sols' then
                fail "No valid allocation solutions"
            else
                return $ map (\(x, y) -> (fromJust x, y)) sols'

processResults :: (Monad m) => [(NodeList, [Node.Node])]
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
  (opts, args) <- CLI.parseOpts cmd_args "hail" options
                  defaultOptions

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
                                     map ((++ csf) . name) sn)
               Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rn
  putStrLn resp
