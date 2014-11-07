Code style guide
================

Python
------

.. highlight:: python

These are a few guidelines for Ganeti code and documentation.

In simple terms: try to stay consistent with the existing code. `PEP 8`_ says:

.. _PEP 8: http://www.python.org/dev/peps/pep-0008/

  A style guide is about consistency. Consistency with this style guide is
  important. Consistency within a project is more important. Consistency
  within one module or function is most important.

.. note::

  You might also want to take a look at the `Google style guide`_, since we
  have some things in common with it.

.. _Google style guide: http://google-styleguide.googlecode.com/svn/trunk/pyguide.html

Indentation
~~~~~~~~~~~
In general, always indent using two (2) spaces and don't use tabs.

The two spaces should always be relative to the previous level of indentation,
even if this means that the final number of spaces is not a multiple of 2.

When going on a new line inside an open parenthesis, align with the content of
the parenthesis on the previous line.

Valid example::

  v = (somevalue,
       a_function([
         list_elem, # 7 spaces, but 2 from the previous indentation level
         another_elem,
       ]))

Formatting strings
~~~~~~~~~~~~~~~~~~
Always use double quotes (``""``), never single quotes (``''``), except for
existing code. Examples for formatting strings::

  var = "value"

  # Note: The space character is always on the second line
  var = ("The quick brown fox jumps over the lazy dog. The quick brown fox"
         " jumps over the lazy dog. The quick brown fox jumps over the lazy"
         " dog.")

  fn("The quick brown fox jumps over the lazy dog. The quick brown fox jumps"
     " over the lazy dog.")

  fn(constants.CONFIG_VERSION,
     ("The quick brown fox jumps over the lazy dog. The quick brown fox"
      " jumps over the lazy dog. The quick brown fox jumps over the lazy"
      " dog."))

Don't format strings like this::

  # Don't use single quotes
  var = 'value'

  # Don't use backslash for line continuation
  var = "The quick brown fox jumps over the lazy dog. The quick brown fox"\
        " jumps over the lazy dog."

  # Space character goes to the beginning of a new line
  var = ("The quick brown fox jumps over the lazy dog. The quick brown fox "
         "jumps over the lazy dog. The quick brown fox jumps over the lazy "
         "dog.")

Formatting sequences
~~~~~~~~~~~~~~~~~~~~
Built-in sequence types are list (``[]``), tuple (``()``) and dict (``{}``).
When splitting to multiple lines, each item should be on its own line and a
comma must be added on the last line. Don't write multiline dictionaries in
function calls, except when it's the only parameter. Always indent items by
two spaces.

::

  # Short lists
  var = ["foo", "bar"]
  var = ("foo", "bar")

  # Longer sequences and dictionary
  var = [
    constants.XYZ_FILENAME_EXTENSION,
    constants.FOO_BAR_BAZ,
    ]
  var = {
    "key": func(),
    "otherkey": None,
    }

  # Multiline tuples as dictionary values
  var = {
    "key":
      ("long value taking the whole line, requiring you to go to a new one",
       other_value),
  }

  # Function calls
  var = frozenset([1, 2, 3])
  var = F({
    "xyz": constants.XYZ,
    "abc": constants.ABC,
    })

  # Wrong
  F(123, "Hello World",
    { "xyz": constants.XYZ })

We consider tuples as data structures, not containers. So in general please
use lists when dealing with a sequence of homogeneous items, and tuples when
dealing with heterogeneous items.

Passing arguments
~~~~~~~~~~~~~~~~~
Positional arguments must be passed as positional arguments, keyword arguments
must be passed as keyword arguments. Everything else will be difficult to
maintain.

::

  # Function signature
  def F(data, key, salt=None, key_selector=None):
    pass

  # Yes
  F("The quick brown fox", "123456")
  F("The quick brown fox", "123456", salt="abc")
  F("The quick brown fox", "123456", key_selector="xyz")
  F("The quick brown fox", "123456", salt="foo", key_selector="xyz")

  # No: Passing keyword arguments as positional argument
  F("The quick brown fox", "123456", "xyz", "bar")

  # No: Passing positional arguments as keyword argument
  F(salt="xyz", data="The quick brown fox", key="123456", key_selector="xyz")

Docstrings
~~~~~~~~~~

.. note::

  `PEP 257`_ is the canonical document, unless epydoc overrules it (e.g. in how
  to document the type of an argument).

For docstrings, the recommended format is epytext_, to be processed via
epydoc_. There is an ``apidoc`` target that builds the documentation and puts it
into the doc/api subdir. Note that we currently use epydoc version 3.0.

.. _PEP 257: http://www.python.org/dev/peps/pep-0257/
.. _epytext: http://epydoc.sourceforge.net/manual-epytext.html
.. _epydoc: http://epydoc.sourceforge.net/

Note that one-line docstrings are only accepted in the unittests.

Rules for writing the docstrings (mostly standard Python rules):

* the docstring should start with a sentence, with punctuation at the end,
  summarizing the the aim of what is being described. This sentence cannot be
  longer than one line
* the second line should be blank
* afterwards the rest of the docstring
* special epytext tags should come at the end
* multi-line docstrings must finish with an empty line
* do not try to make a table using lots of whitespace
* use ``L{}`` and ``C{}`` where appropriate

Here's an example::

  def fn(foo, bar):
    """Compute the sum of foo and bar.

    This functions builds the sum of foo and bar. It's a simple function.

    @type foo: int
    @param foo: First parameter.
    @type bar: float
    @param bar: The second parameter. This line is longer
      to show wrapping.
    @rtype: float
    @return: the sum of the two numbers

    """
    return foo + bar

Some rules of thumb which should be applied with good judgement on a case-to-
case basis:

* If the meaning of parameters is already obvious given its name and the
  methods description, don't document it again. Just add a ``@type`` tag.
* Refer to the base methods documentation when overwriting methods. Only
  document more if it applies to the current subclass only, or if you want to
  clarify on the meaning of parameters for the special subclass.

Rules for classes and modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
As `PEP 257`_ says, the docstrings of classes should document their attributes
and the docstrings of modules should shortly document the exported
functions/variables/etc.

See for example the pydoc output for the ``os`` or ``ConfigParser`` standard
modules.

Haskell
-------

.. highlight:: haskell

The most important consideration is, as usual, to stay consistent with the
existing code.

As there's no "canonical" style guide for Haskell, this code style has been
inspired from a few online resources, including the style guide for the
`Snap framework`_, `this style guide`_ and `this other style guide`_.

.. _Snap framework: http://snapframework.com/docs/style-guide
.. _this style guide: https://github.com/tibbe/haskell-style-guide/blob/master/haskell-style.md
.. _this other style guide: http://www.cs.caltech.edu/courses/cs11/material/haskell/misc/haskell_style_guide.html

Files
~~~~~
Use ordinary, non-`literate`_ Haskell ``.hs`` files.

.. _literate: http://www.haskell.org/haskellwiki/Literate_programming

Use proper copyright headers, and proper Haddock style documentation headers::

  {-| Short module summary.

  Longer module description.

  -}

  {-

  Copyright (C) ...

  This program is free software ...

  -}

If there are module-level pragmas add them right at the top, before the short
summary.

Imports
~~~~~~~
Imports should be grouped into the following groups and inside each group they
should be sorted alphabetically:

1. import of non-Ganeti libaries
2. import of Ganeti libraries

It is allowed to use qualified imports with short names for:

* standard library (e.g. ``import qualified Data.Map as M``)
* local imports (e.g. ``import qualified Ganeti.Constants as C``)

Whenever possible, prefer explicit imports, either in form of
qualified imports, or by naming the imported functions
(e.g., ``import Control.Arrow ((&&&))``, ``import Data.Foldable(fold, toList)``)

Indentation
~~~~~~~~~~~
Use only spaces, never tabs. Indentation level is 2 characters. For Emacs,
this means setting the variable ``haskell-indent-offset`` to 2.

Line length should be at most 78 chars, and 72 chars inside comments.

Use indentation-based structure, and not braces/semicolons.

.. note::

  Special indendation of if/then/else construct

  For the ``do`` notation, the ``if-then-else`` construct has a non-intuitive
  behaviour. As such, the indentation of ``if-then-else`` (both in ``do``
  blocks and in normal blocks) should be as follows::

    if condition
      then expr1
      else expr2

  i.e. indent the then/else lines with another level. This can be accomplished
  in Emacs by setting the variable ``haskell-indent-thenelse`` to 2 (from the
  default of zero).

If you have more than one line of code please newline/indent after the "=". Do
`not` do::

  f x = let y = x + 1
        in  y

Instead do::

  f x =
    let y = x + 1
    in  y

or if it is just one line::

  f x = x + 1

Multiline strings
~~~~~~~~~~~~~~~~~
Multiline strings are created by closing a line with a backslash and starting
the following line with a backslash, keeping the indentation level constant.
Whitespaces go on the new line, right after the backslash.

::

  longString :: String
  longString = "This is a very very very long string that\
               \ needs to be split in two lines"

Data declarations
~~~~~~~~~~~~~~~~~
.. warning::
  Note that this is different from the Python style!

When declaring either data types, or using list literals, etc., the columns
should be aligned, and for lists use a comma at the start of the line, not at
the end. Examples::

  data OpCode = OpStartupInstance ...
              | OpShutdownInstance ...
              | ...

  data Node = Node { name :: String
                   , ip   :: String
                   , ...
                   }

  myList = [ value1
           , value2
           , value3
           ]

The choice of whether to wrap the first element or not is up to you; the
following is also allowed::

  myList =
    [ value1
    , value2
    ]

For records, always add spaces around the braces and the equality sign.
::

  foo = Foo { fBar = "bar", fBaz = 4711 }

  foo' = Foo { fBar = "bar 2"
             , fBaz = 4712
             }

  node' = node { ip = "127.0.0.1" }


White space
~~~~~~~~~~~
Like in Python, surround binary operators with one space on either side. Do no
insert a space after a lamda::

  -- bad
  map (\ n -> ...) lst
  -- good
  foldl (\x y -> ...) ...

Use a blank line between top-level definitions, but no blank lines between
either the comment and the type signature or between the type signature and
the actual function definition.

.. note::
  Ideally it would be two blank lines between top-level definitions, but the
  code only has one now.

As always, no trailing spaces. Ever.

Spaces after comma
******************

Instead of::

  ("a","b")

write::

  ("a", "b")

Naming
~~~~~~
Functions should be named in mixedCase style, and types in CamelCase. Function
arguments and local variables should be mixedCase.

When using acronyms, ones longer than 2 characters should be typed capitalised,
not fully upper-cased (e.g. ``Http``, not ``HTTP``).

For variable names, use descriptive names; it is only allowed to use very
short names (e.g. ``a``, ``b``, ``i``, ``j``, etc.) when:

* the function is trivial, e.g.::

    sum x y = x + y

* we talk about some very specific cases, e.g.
  iterators or accumulators in folds::

    map (\v -> v + 1) lst

* using ``x:xs`` for list elements and lists, etc.

In general, short/one-letter names are allowed when we deal with polymorphic
values; for example the standard map definition from Prelude::

  map :: (a -> b) -> [a] -> [b]
  map _ []     = []
  map f (x:xs) = f x : map f xs

In this example, neither the ``a`` nor ``b`` types are known to the map
function, so we cannot give them more explicit names. Since the body of the
function is trivial, the variables used are longer.

However, if we deal with explicit types or values, their names should be
descriptive.

.. todo: add a nice example here.

Finally, the naming should look familiar to people who just read the
Prelude/standard libraries.

Naming for updated values
*************************

.. highlight:: python

Since one cannot update a value in Haskell, this presents a particular problem
on the naming of new versions of the same value. For example, the following
code in Python::

  def failover(pri, sec, inst):
    pri.removePrimary(inst)
    pri.addSecondary(inst)
    sec.removeSecondary(inst)
    sec.addPrimary(inst)

.. highlight:: haskell

becomes in Haskell something like the following::

  failover pri sec inst =
    let pri'  = removePrimary pri inst
        pri'' = addSecondary pri' inst
        sec'  = removeSecondary sec inst
        sec'' = addPrimary sec' inst
    in (pri'', sec'')

When updating values, one should add single quotes to the name for up to three
new names (e.g. ``inst``, ``inst'``, ``inst''``, ``inst'''``) and otherwise
use numeric suffixes (``inst1``, ``inst2``, ``inst3``, ..., ``inst8``), but
that many updates is already bad style and thus should be avoided.

Type signatures
~~~~~~~~~~~~~~~

Always declare types for functions (and any other top-level bindings).

If in doubt, feel free to declare the type of the variables/bindings in a
complex expression; this usually means the expression is too complex, however.

Similarly, provide Haddock-style comments for top-level definitions.

Use sum types instead of exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Exceptions make it hard to write functional code, as alternative
control flows need to be considered and compiler support is limited.
Therefore, Ganeti functions should never allow exceptions to escape.
Function that can fail should report failure by returning an appropriate
sum type (``Either`` or one of its glorified variants like ``Maybe`` or
``Result``); the preferred sum type for reporting errors is ``Result``.

As other Ganeti functions also follow these guide lines, they can safely
be composed. However, be careful when using functions from other libraries;
if they can raise exceptions, catch them, preferably as close to their
origin as reasonably possible.

Parentheses, point free style
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prefer the so-called `point-free`_ style style when declaring functions, if
applicable::

  -- bad
  let a x = f (g (h x))
  -- good
  let a = f . g . h

Also use function composition in a similar manner in expressions to avoid extra
parentheses::

  -- bad
  f (g (h x))
  -- better
  f $ g $ h x
  -- best
  f . g . h $ x

.. _`point-free`: http://www.haskell.org/haskellwiki/Pointfree

Language features
~~~~~~~~~~~~~~~~~

Extensions
**********

It is recommended to keep the use of extensions to a minimum, so that the code
can be understood even if one is familiar with just Haskel98/Haskell2010. That
said, some extensions are very common and useful, so they are recommended:

* `Bang patterns`_: useful when you want to enforce strict evaluation (and better
  than repeated use of ``seq``)
* CPP: a few modules need this in order to account for configure-time options;
  don't overuse it, since it breaks multi-line strings
* `Template Haskell`_: we use this for automatically deriving JSON instances and
  other similar boiler-plate

.. _Bang patterns: http://www.haskell.org/ghc/docs/latest/html/users_guide/bang-patterns.html
.. _Template Haskell: http://www.haskell.org/ghc/docs/latest/html/users_guide/template-haskell.html

Such extensions should be declared using the ``Language`` pragma::

  {-# Language BangPatterns #-}

  {-| This is a small module... -}

Comments
********

Always use proper sentences; start with a capital letter and use punctuation
in top level comments::

  -- | A function that does something.
  f :: ...

For inline comments, start with a capital letter but no ending punctuation.
Furthermore, align the comments together with a 2-space width from the end of
the item being commented::

  data Maybe a = Nothing  -- ^ Represents empty container
               | Just a   -- ^ Represents a single value

The comments should be clear enough so that one doesn't need to look at the
code to understand what the item does/is.

Use ``-- |`` to write doc strings rather than bare comment with ``--``.

Tools
*****

We generate the API documentation via Haddock, and as such the comments should
be correct (syntax-wise) for it. Use markup, but sparingly.

We use hlint_ as a lint checker; the code is currently lint-clean, so you must
not add any warnings/errors.

.. _hlint: http://community.haskell.org/~ndm/darcs/hlint/hlint.htm

Use these two commands during development::

  make hs-apidoc
  make hlint

QuickCheck best practices
*************************

If you have big type that takes time to generate and several properties to
test on that, by default 500 of those big instances are generated for each
property. In many cases, it would be sufficient to only generate those 500
instances once and test all properties on those. To do this, create a property
that uses ``conjoin`` to combine several properties into one. Use
``counterexample`` to add expressive error messages. For example::

  prop_myMegaProp :: myBigType -> Property
  prop_myMegaProp b =
    conjoin
      [ counterexample
          ("Something failed horribly here: " ++ show b) (subProperty1 b)
      , counterexample
          ("Something else failed horribly here: " ++ show b)
          (subProperty2 b)
      , -- more properties here ...
      ]

  subProperty1 :: myBigType -> Bool
  subProperty1 b = ...

  subProperty2 :: myBigType -> Property
  subProperty2 b = ...

  ...

Maybe Generation
''''''''''''''''

Use ``genMaybe genSomething`` to create ``Maybe`` instances of something
including some ``Nothing`` instances.

Use ``Just <$> genSomething`` to generate only ``Just`` instances of
something.

String Generation
'''''''''''''''''

To generate strings, consider using ``genName`` instead of ``arbitrary``.
``arbitrary`` has the tendency to generate strings that are too long.
