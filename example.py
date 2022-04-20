#!/usr/bin/env python3

from pyrenode import connect_renode, get_keywords
connect_renode(robot_port=4444)
get_keywords(robot_port=4444)

uart = 'sysbus.usart1'
ExecuteCommand('i @scripts/single-node/sam_e70.resc')
CreateTerminalTester(uart)
ExecuteCommand(f"showAnalyzer {uart}")
StartEmulation()
WaitForPromptOnUart("uart:~")
WriteLineToUart("version")
WaitForLineOnUart("Zephyr* version 1.14.0-rc1", timeout=60, treatAsRegex=True)
print(ExecuteCommand('help'))
