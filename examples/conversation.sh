#!/usr/bin/env bash

# This isn't necessary, it's just to stylize the output of tollcalling
function stream_parser() {
	{
    jq -r '
        if .class == "toolcall" and .message == "request"
        then
            "**" + .obj.function.name + ":**\n\n```shell\n"
            + (.obj.function.arguments | fromjson | to_entries
               | map("  \(.key): \(.value)") | join("\n")) +
						"\n```\n"
        elif .message == "result"
        then .obj.content[0].text
        else empty
        end'
	} | sd
}

conv=${CONV:-$(mktemp)}

echo -e "  Using: $conv\n"
jq -r '.[] | "\n**\(.role)**: \(.content)"' $conv | tail -100 | sd
while builtin read -p "  >> " query; do 
  llcat -c $conv "$@" "$query" 2> >(stream_parser) | sd
  echo
done
