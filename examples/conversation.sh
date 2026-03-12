#!/usr/bin/env bash
conv=${CONV:-$(mktemp)}
echo -e "  Using: $conv\n"
jq -r '.[] | "\n**\(.role)**: \(.content)"' $conv | tail -100 | sd
while builtin read -p "  >> " query; do 
    llcat -c $conv "$@" "$query" | sd
    echo
done
