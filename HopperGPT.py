import urllib.request
import json
import re
import gc

OPENAI_API_KEY = 'YOUR_OPENAI_API_KEY'
ALWAYS_ANSWER_IN_LANGUAGE = 'ENGLISH'

IGNORED_CLASS_PREFIXES = [
    'AFNetwork', 'AFHTTP', 'AFURL', 'AFSecurity',
    'Flurry', 'FMDatabase',
    'MBProgressHUD', 'MJ',
    'SDWebImage',
]

IGNORED_CLASS_LABEL_NAMES = [
    '-[ClassName methodName:]',
]

class CodeExplainer:

    _end_flag = '-'.join(['-' for _ in range(54)])
    def __init__(self, document):
        self.document = document
        self.current_segment = document.getCurrentSegment()
        self.current_procedure = document.getCurrentProcedure()
        self.segment = self._get_text_segment()

    def _get_text_segment(self):
        segment = self.document.getSegmentByName('__TEXT')
        if not segment:
            segment = self.document.getSegmentsList()[0]
        return segment

    def _is_ignored_class(self, class_name):
        return any(class_name.startswith(prefix) for prefix in IGNORED_CLASS_PREFIXES)

    def _is_ignored_method(self, label_name):
        return label_name in IGNORED_CLASS_LABEL_NAMES

    def _parse_label_name(self, label_name):
        result = re.search(r'^([+-])\[(.+)\s(.+)\]', label_name)
        if result:
            symbol, class_name, method_name = result.groups()
            params_count = method_name.count(':')
            params = ', '.join([f'arg{i+2}: Any' for i in range(params_count)])
            method_name = method_name.replace(':', ' ')  # Remove colon for Swift method signature
            method_name = f'{symbol}{method_name}'
            return class_name, method_name, params
        else:
            return None, None, None
        
    def _splitted_to_multiple_line(self, text):

        MAX_LINE_LENGTH = 120
        lines = []

        # Split description into lines
        description_lines = text.split('\n')

        for line in description_lines:
            # Determine indentation dynamically for each line
            indentation = len(line) - len(line.lstrip())

            if len(line) > MAX_LINE_LENGTH:
                # Split line by words while maintaining indentation
                words = line.split()
                current_line = ''
                for word in words:
                    if len(current_line) + len(word) + 1 <= MAX_LINE_LENGTH:
                        # Add word to current line if it doesn't exceed the max length
                        if current_line:
                            current_line += ' ' + word
                        else:
                            current_line = word
                    else:
                        # Add current line with indentation to lines
                        lines.append(' ' * indentation + current_line)
                        # if current_line and (current_line[0] == '-') or (current_line[0] == ' ') or current_line[0].isdigit():
                        #     current_line = ' ' + word
                        # else:
                        current_line = word
                # Add remaining part of line
                lines.append(' ' * indentation + current_line)
            else:
                # Add line with indentation to lines
                lines.append(line)

        # Join the lines back together
        return '\n'.join(lines)

    def _ask_gpt(self, prompt):
        url = 'https://api.openai.com/v1/chat/completions'
        data = {"messages":[ {"role": "user","content":prompt} ], "model": "gpt-3.5-turbo"}
        data = json.dumps(data).encode('utf-8')

        req = urllib.request.Request(url, data,
                            {'Authorization': 'Bearer ' + OPENAI_API_KEY,
                            'Content-Type': 'application/json'})
        response = urllib.request.urlopen(req)
        response_data = response.read()
        response_data = json.loads(response_data)

        if "error" in response:
            raise ValueError(response_data["error"])
        else:
            return response_data["choices"][0]["message"]["content"]

    def explain_class(self, input_class_name=None):
        classes = self._get_classes(input_class_name)
        total_count = sum(len(procedures) for procedures in classes.values())

        print('[-] Total method found :', total_count)

        for class_name, procedures in classes.items():
            print(f'\n***** START {class_name} *****')
            codes = self._generate_pseudo_codes(procedures)
            print(f"Explaining class name {class_name}:\n{codes}\n***** END {class_name} *****")
            description = self._ask_gpt(f"""
Can you describe and breakdown what class {class_name} does? and don't forget to explain the instruction set meaning in the pseudo code
Here is pseudo code:
{codes}
Always respond in {ALWAYS_ANSWER_IN_LANGUAGE}
""")
            print(f"Description for class {class_name}: \n{description}\n{self._end_flag}\n")
            del codes
            gc.collect()

    def _get_classes(self, input_class_name=None):
        classes = {}
        for i in range(self.segment.getProcedureCount()):
            procedure = self.segment.getProcedureAtIndex(i)
            address = procedure.getEntryPoint()

            label_name = self.segment.getNameAtAddress(address)
            if not label_name or self._is_ignored_method(label_name):
                continue

            class_name, method_name, params = self._parse_label_name(label_name)
            if not class_name or (input_class_name and class_name != input_class_name) or self._is_ignored_class(class_name):
                continue

            procedure.label_name = label_name
            procedure.method_name = method_name
            procedure.params = params
            classes.setdefault(class_name, []).append(procedure)

        return classes

    def _generate_pseudo_codes(self, procedures):
        codes = ''
        for procedure in procedures:
            pseudo_code = procedure.decompile()
            if pseudo_code:
                method_signature = f'func {procedure.method_name}({procedure.params})'
                codes += f'{method_signature} {{\n{pseudo_code}\n}}\n\n'
        return codes

    def explain_pseudo_procedure(self):
        current_procedure = self.current_procedure
        if not current_procedure:
            print("[-] Oppss.. No current procedure found.")
            return
        
        method_name, class_name, _, _, codes = self._get_procedure_info(current_procedure)

        print(f"Explaining procedure{method_name} at address {hex(current_procedure.getEntryPoint())}{class_name}:\n{codes}")
        description = self._ask_gpt(f"""
Can you describe and breakdown what this procedure does? include parameters? and don't forget to explain the instruction set meaning in the pseudo code
Here is pseudo code:
{codes}
Always respond in {ALWAYS_ANSWER_IN_LANGUAGE}
""")
        print(f"Description for method{method_name} at address {hex(current_procedure.getEntryPoint())}{class_name}: \n{description}\n{self._end_flag}\n")
        del codes
        gc.collect()

    def explain_asm_procedure(self):
        current_procedure = self.current_procedure
        if not current_procedure:
            print("[-] Oppss.. No current procedure found.")
            return
        
        for index in range(current_procedure.getBasicBlockCount()):
            method_name, class_name, _, address, asm_codes = self._get_procedure_info(current_procedure, asm=True, index=index)
            if not asm_codes:
                description = "Sorry, I can't recognize this procedure instruction set."
                self.current_segment.setCommentAtAddress(address, description)
                continue

            print(f"{index+1}. Explaining procedure{method_name} instruction set at address {hex(address)}{class_name}:\n{asm_codes}")
            description = self._ask_gpt(f"""
Can you describe and breakdown what this procedure asm code does? include parameters, variables, and instructions set meaning in the asm code.
Here is asm code:
{asm_codes}
Always respond in {ALWAYS_ANSWER_IN_LANGUAGE} languages
""")
            print(f"Description for instruction set at address {hex(current_procedure.getEntryPoint())}{class_name}: \n{description}\n{self._end_flag}\n")
            description = self._splitted_to_multiple_line(description)

            self.current_segment.setCommentAtAddress(address, description)
            del asm_codes
            gc.collect()

    def _get_procedure_info(self, procedure, asm=False, index=0):
        address = procedure.getEntryPoint()
        label_name = self.segment.getNameAtAddress(address)

        class_name, method_name, params = self._parse_label_name(label_name)
        class_name = '' if class_name is None else f' in class {class_name}'
        method_name = '' if method_name is None else f' func {method_name}'
        params = '' if params is None else f'({params})'

        codes = ''
        if asm:  # Generate assembly code
            (address, codes) = self._generate_asm_codes(procedure, index)
        else:    # Generate pseudo code
            pseudo_code = procedure.decompile()
            if pseudo_code is not None:  # Check if decompilation was successful
                method_signature = f'{method_name}{params}'
                codes = f'{method_signature} {{\n{pseudo_code}\n}}\n\n'
        return method_name, class_name, params, address, codes

    def _generate_asm_codes(self, procedure, index):
        asm_codes = ''
        basic_block = procedure.getBasicBlock(index)                
        starting_address = basic_block.getStartingAddress()        
        ending_address = basic_block.getEndingAddress()
                
        current_address = starting_address
        while current_address < ending_address:

            instruction = self.current_segment.getInstructionAtAddress(current_address)

            if instruction:
                instruction_string = f"0x{current_address:X}: " + instruction.getInstructionString()                
                argCount = instruction.getArgumentCount()

                if argCount >= 0:

                    for idx in range(argCount):
                        instruction_string += " " + instruction.getFormattedArgument(idx)
                            
                    if instruction.isAConditionalJump():
                            instruction_string += "; Conditional Jump"

                    if instruction.isAnInconditionalJump():
                            instruction_string += "; Inconditional Jump"

                    asm_codes += instruction_string + "\n"
                current_address += instruction.getInstructionLength()
            else:
                current_address += 1
        return (starting_address, asm_codes)

document = Document.getCurrentDocument()
explainer = CodeExplainer(document)

# Ask user to select type of explanation
line = ''.join(['-'] * 120)
message = f'''
{line}
1. All Classes: Will find all classes in the document and explain their methods based on the generated pseudo code.
2. Input Class Name: Will explain the input class name and its methods based on the generated pseudo code.
3. Pseudo Code: Will explain the current procedure by generating pseudo code.
4. ASM Instruction: Will explain the ASM instruction set for the current procedure.
5. Cancel
{line}
[-] Select the type of explanation:
'''
buttons = ['[1] All Classes', '[2] Input Class Name', '[3] Pseudo Code', '[4] ASM Instruction', '[5] Cancel']
button_index = document.message(message, buttons)
if button_index == 0:
    explainer.explain_class()
elif button_index == 1:
    message = 'Please input the class name:'
    input_class_name = document.ask(message)
    if input_class_name is None:
        print('Cancel Explaining!')
    elif input_class_name == '':
        print('Class name cannot be empty!')
    else:
        explainer.explain_class(input_class_name)
elif button_index == 2:
    explainer.explain_pseudo_procedure()
elif button_index == 3:
    explainer.explain_asm_procedure()
elif button_index == 4:
    print('[-] Cancel Explaining!')
