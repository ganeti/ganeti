{-| Custom hint lints for Ganeti.

Since passing --hint to hlint will override, not extend the built-in
hints, we need to import the existing hints so that we get full
coverage.

-}

import "hint" HLint.HLint
import "hint" HLint.Dollar

-- The following two hints warn to simplify e.g. "map (\v -> (v,
-- True)) lst" to "zip lst (repeat True)", which is more abstract
warn = map (\v -> (v, x)) y ==> zip y (repeat x)
  where _ = notIn v x
warn = map (\v -> (x, v)) ==> zip (repeat x)
  where _ = notIn v x

-- The following warn on use of length instead of null
warn = length x > 0 ==> not (null x)
warn = length x /= 0 ==> not (null x)
warn = length x == 0 ==> null x

-- Never use head, use 'case' which covers all possibilities
warn = head x ==> case x of { y:_ -> y } where note = "Head is unsafe, please use case and handle the empty list as well"

-- Never use tail, use 'case' which covers all possibilities
warn = tail x ==> case x of { _:y -> y } where note = "Tail is unsafe, please use case and handle the empty list as well"

ignore "Use first"
ignore "Use &&&"
ignore "Use &&"
ignore "Reduce duplication"
ignore "Use import/export shortcut"

-- FIXME: remove ignore "Use void" when GHC 6.x is deprecated
ignore "Use void"

-- Configure newer HLint 1.9.26 to behave like older versions
-- FIXME: Cleanup code and remove this
ignore "Redundant bracket"
ignore "Functor law"
