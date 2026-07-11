#!/usr/bin/env python3
"""Realistic per-language source samples for the highlighter golden tests.

`SAMPLES` maps each `highlight_code.LANGUAGE_CONFIGS` language to a representative
snippet that exercises keywords, strings, numbers, function calls, operators, and
(where the language has them) line and block comments. `build_highlight_fixtures.py`
turns each sample into a checked-in, pre-annotated golden file under `fixtures/`;
`test_highlight_golden.py` re-runs the highlighter and compares against those goldens.
"""

SAMPLES = {
    "python": '''\
import math


def area(radius):
    """Return the area of a circle."""
    pi = 3.14159  # not math.pi on purpose
    return pi * radius ** 2


class Circle:
    def __init__(self, r):
        self.r = r

    def describe(self):
        return f"circle r={self.r} area={area(self.r):.2f}"
''',
    "javascript": '''\
// Fibonacci with memoization
const cache = new Map();

function fib(n) {
  if (n < 2) return n;
  if (cache.has(n)) return cache.get(n);
  const value = fib(n - 1) + fib(n - 2);
  cache.set(n, value);
  return value;
}

/* Print the first 10 numbers */
for (let i = 0; i < 10; i++) {
  console.log(`fib(${i}) = ${fib(i)}`);
}
''',
    "typescript": '''\
interface User {
  id: number;
  name: string;
}

// Look up a user by id
function findUser(users: User[], id: number): User | undefined {
  return users.find((u) => u.id === id);
}

const users: User[] = [{ id: 1, name: "Ada" }];
/* Log the result */
console.log(findUser(users, 1)?.name ?? "unknown");
''',
    "json": '''\
{
  "name": "commentable-html",
  "version": "1.3.0",
  "enabled": true,
  "retries": 3,
  "tags": ["review", "html"],
  "author": { "name": "Uri", "email": "urikanonov@gmail.com" }
}
''',
    "bash": '''\
#!/usr/bin/env bash
set -euo pipefail

# Count lines in each tracked file
total=0
for file in $(git ls-files); do
  lines=$(wc -l < "$file")
  echo "$file: $lines"
  total=$((total + lines))
done

echo "total lines: $total"
''',
    "sql": '''\
-- Top customers by revenue
SELECT c.id, c.name, SUM(o.amount) AS revenue
FROM customers AS c
INNER JOIN orders AS o ON o.customer_id = c.id
WHERE o.status = 'paid'
GROUP BY c.id, c.name
HAVING SUM(o.amount) > 1000
ORDER BY revenue DESC
LIMIT 10;
/* revenue is in cents */
''',
    "csharp": '''\
using System;

namespace Demo
{
    // A simple greeter
    public class Greeter
    {
        public string Name { get; }
        public int Visits { get; } = 0;

        public Greeter(string name) => Name = name;

        public string Greet()
        {
            /* interpolated string */
            return $"Hello, {Name}! You are visitor 42.";
        }
    }
}
''',
    "java": '''\
import java.util.List;

public class Sum {
    // Add all values in the list
    public static int total(List<Integer> values) {
        int sum = 0;
        for (int v : values) {
            sum += v;
        }
        return sum;
    }

    public static void main(String[] args) {
        /* prints 6 */
        System.out.println(total(List.of(1, 2, 3)));
    }
}
''',
    "go": '''\
package main

import "fmt"

// Greet builds a greeting string.
func Greet(name string) string {
	return fmt.Sprintf("hello, %s", name)
}

func main() {
	names := []string{"ada", "grace"}
	for i, n := range names {
		/* one line per name */
		fmt.Println(i, Greet(n))
	}
	fmt.Println("count:", len(names)*2)
}
''',
    "yaml": '''\
# CI pipeline
name: build
on:
  push:
    branches: ["main"]
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - run: python -m pytest
''',
    "c": '''\
#include <stdio.h>

/* Greatest common divisor */
int gcd(int a, int b) {
    while (b != 0) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a; // Euclid
}

int main(void) {
    printf("gcd = %d\\n", gcd(48, 36));
    return 0;
}
''',
    "cpp": '''\
#include <iostream>
#include <vector>

// Sum a vector of ints
int sum(const std::vector<int>& xs) {
    int total = 0;
    for (auto x : xs) {
        total += x;
    }
    return total; /* accumulate */
}

int main() {
    std::vector<int> xs = {1, 2, 3};
    std::cout << sum(xs) << "\\n";
}
''',
    "xml": '''\
<?xml version="1.0" encoding="UTF-8"?>
<!-- Sample configuration -->
<config>
  <server host="localhost" port="8080" />
  <feature name="highlight" enabled="true" />
  <retries>3</retries>
</config>
''',
    "html": '''\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Demo</title>
  </head>
  <body>
    <!-- greeting -->
    <main class="content">
      <h1>Hello</h1>
      <button onclick="alert('hi')">Click 42</button>
    </main>
  </body>
</html>
''',
    "rust": '''\
use std::collections::HashMap;

// Count word frequencies
fn word_counts(text: &str) -> HashMap<&str, u32> {
    let mut counts = HashMap::new();
    for word in text.split_whitespace() {
        *counts.entry(word).or_insert(0) += 1;
    }
    counts
}

fn main() {
    let counts = word_counts("a b a c a");
    /* prints 3 for "a" */
    println!("{}", counts["a"]);
}
''',
    "ruby": '''\
# Simple stack implementation
class Stack
  def initialize
    @items = []
  end

  def push(value)
    @items << value
  end

  def pop
    @items.pop
  end
end

stack = Stack.new
stack.push(42)
puts "top = #{stack.pop}"
''',
    "php": '''\
<?php

// Sum an array of numbers
function total(array $values): int {
    $sum = 0;
    foreach ($values as $value) {
        $sum += $value;
    }
    return $sum; /* fold */
}

$numbers = [1, 2, 3];
echo "total = " . total($numbers) . "\\n";
''',
    "swift": '''\
import Foundation

// Fibonacci sequence
func fib(_ n: Int) -> Int {
    if n < 2 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

let values = (0..<10).map { fib($0) }
/* prints the sequence */
print("fib:", values)
''',
    "kotlin": '''\
// Greeting helper
fun greet(name: String): String {
    return "Hello, $name!"
}

fun main() {
    val names = listOf("Ada", "Grace")
    for (name in names) {
        /* one line each */
        println(greet(name))
    }
    val count = 42
    println("count = $count")
}
''',
    "scala": '''\
object Demo {
  // Sum a list recursively
  def sum(xs: List[Int]): Int = xs match {
    case Nil => 0
    case head :: tail => head + sum(tail)
  }

  def main(args: Array[String]): Unit = {
    /* prints 6 */
    val values = List(1, 2, 3)
    println(s"sum = ${sum(values)}")
  }
}
''',
    "dart": '''\
// Fibonacci generator
int fib(int n) {
  if (n < 2) {
    return n;
  }
  return fib(n - 1) + fib(n - 2);
}

void main() {
  final values = [for (var i = 0; i < 10; i++) fib(i)];
  /* prints the list */
  print("fib: $values");
}
''',
    "r": '''\
# Summary statistics helper
summarize <- function(x) {
  m <- mean(x)
  s <- sd(x)
  sprintf("mean=%.2f sd=%.2f", m, s)
}

values <- c(1, 2, 3, 4, 5)
message(summarize(values))
print(length(values))
''',
    "perl": '''\
#!/usr/bin/perl
use strict;
use warnings;

# Count words on each line
my %counts;
while (my $line = <STDIN>) {
    for my $word (split /\\s+/, $line) {
        next if length($word) < 2;
        $counts{$word}++;
    }
}

for my $word (sort keys %counts) {
    print "$word: $counts{$word}\\n";
}
''',
    "powershell": '''\
# Report large files in a folder
function Get-LargeFiles {
    param(
        [string]$Path,
        [int]$MinBytes = 1024
    )

    <# filter and sort #>
    Get-ChildItem -Path $Path -File |
        Where-Object { $_.Length -gt $MinBytes } |
        Sort-Object Length -Descending
}

Get-LargeFiles -Path "." -MinBytes 42 | Format-Table Name, Length
''',
    "lua": '''\
-- Recursive factorial
local function factorial(n)
  if n <= 1 then
    return 1
  end
  return n * factorial(n - 1)
end

--[[
  Print factorials from 1 to 5
]]
for i = 1, 5 do
  print(string.format("%d! = %d", i, factorial(i)))
end
''',
    "toml": '''\
# Project metadata
[package]
name = "demo"
version = "1.3.0"
enabled = true

[dependencies]
serde = "1.0"
retries = 3

[server]
host = "localhost"
port = 8080
''',
    "css": '''\
/* Theme tokens and layout */
:root {
  --gap: 8px;
  --fg: #1f2328;
}

.card {
  display: flex;
  gap: var(--gap);
  padding: 12px;
  color: var(--fg);
  border-radius: 6px;
}

.card:hover {
  transform: scale(1.02);
}
''',
    "groovy": '''\
// Sum a list of numbers
def total(List<Integer> values) {
    int sum = 0
    for (v in values) {
        sum += v
    }
    return sum
}

def numbers = [1, 2, 3]
/* prints 6 */
println "total = ${total(numbers)}"
''',
    "elixir": '''\
defmodule Fib do
  # Compute the nth Fibonacci number
  def compute(0), do: 0
  def compute(1), do: 1

  def compute(n) when n > 1 do
    compute(n - 1) + compute(n - 2)
  end
end

values = Enum.map(0..9, &Fib.compute/1)
IO.inspect(values, label: "fib")
''',
    "haskell": '''\
module Main where

-- Sum a list of integers
total :: [Int] -> Int
total = foldr (+) 0

{- Entry point -}
main :: IO ()
main = do
  let values = [1, 2, 3]
  putStrLn ("sum = " ++ show (total values))
''',
    "objectivec": '''\
#import <Foundation/Foundation.h>

// A minimal counter
@interface Counter : NSObject
@property (nonatomic) NSInteger count;
- (void)increment;
@end

@implementation Counter
- (void)increment {
    self.count += 1; /* bump */
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Counter *c = [[Counter alloc] init];
        [c increment];
        NSLog(@"count = %ld", (long)c.count);
    }
    return 0;
}
''',
    "batch": '''\
@echo off
rem Greet each argument
setlocal enabledelayedexpansion

set /a count=0
for %%a in (%*) do (
    echo Hello, %%a
    set /a count+=1
)

:: report how many
echo Processed !count! item(s)
endlocal
''',
}
