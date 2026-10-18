#!/usr/bin/env perl
# rename.pl MAP PROTECT [FILE...]
#
# Applies the ordered literal replacements in MAP (FROM<TAB>TO per line) to
# each FILE in place, or filters stdin to stdout when no files are given.
# Tokens listed in PROTECT are swapped for private sentinels first and
# restored last, so a protected token never matches a map entry.
use strict;
use warnings;

my ($map_file, $protect_file, @files) = @ARGV;
die "usage: rename.pl MAP PROTECT [FILE...]\n" unless defined $map_file;

my @map;
open my $mh, '<', $map_file or die "$map_file: $!";
while (my $line = <$mh>) {
    chomp $line;
    next if $line =~ /^\s*(#|$)/;
    my ($from, $to) = split /\t/, $line, 2;
    die "$map_file: bad line (need FROM<TAB>TO): $line\n" unless defined $to;
    push @map, [ $from, $to ];
}
close $mh;

my @protect;
if (defined $protect_file && open my $ph, '<', $protect_file) {
    while (my $line = <$ph>) {
        chomp $line;
        next if $line =~ /^\s*(#|$)/;
        push @protect, $line;
    }
    close $ph;
}

sub transform {
    my ($s) = @_;
    my %sentinel;
    my $i = 0;
    for my $tok (@protect) {
        my $key = "\x{1}CZP" . ($i++) . "\x{1}";
        $sentinel{$key} = $tok;
        my $q = quotemeta $tok;
        $s =~ s/$q/$key/g;
    }
    for my $pair (@map) {
        my $q = quotemeta $pair->[0];
        my $to = $pair->[1];
        $s =~ s/$q/$to/g;
    }
    for my $key (keys %sentinel) {
        my $q = quotemeta $key;
        $s =~ s/$q/$sentinel{$key}/g;
    }
    return $s;
}

if (@files) {
    for my $f (@files) {
        local $/;
        open my $in, '<:raw', $f or die "$f: $!";
        my $content = <$in>;
        close $in;
        $content = '' unless defined $content;
        my $out = transform($content);
        next if $out eq $content;
        open my $oh, '>:raw', $f or die "$f: $!";
        print {$oh} $out;
        close $oh;
    }
} else {
    local $/;
    my $content = <STDIN>;
    $content = '' unless defined $content;
    print transform($content);
}
