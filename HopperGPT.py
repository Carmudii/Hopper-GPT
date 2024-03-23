import urllib.request
import json
import re
import gc

OPENAI_API_KEY = 'YOUR_OPENAI_API_KEY'

class CodeExplainer:
    def __init__(self, document):
        self.document = document
        self.procedure = document.getCurrentProcedure()
        self.segment = document.getSegmentByName('__TEXT')
        if not self.segment:
            self.segment = document.getSegmentsList()[0]

    def parse_label_name(self, label_name):
        result = re.search(r'^([+-])\[(.+)\s(.+)\]', label_name)
        if result:
            symbol, class_name, method_name = result.groups()
            params_count = method_name.count(':')
            params = ', '.join([f'arg{i+2}: Any' for i in range(params_count)])
            method_name = method_name.replace(':', ' ')  # Remove colon for Swift method signature
            method_name = f'{symbol}{method_name}'
            return (class_name, method_name, params)
        else:
            return (None, None, None)

    def ask_gpt(self, prompt):
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

    def explain_procedure(self):
        if not self.procedure:
            print("No current procedure found.")
            return
        
        procedure_entry_point_address = self.procedure.getEntryPoint()
        label_name = self.segment.getNameAtAddress(procedure_entry_point_address)

        class_name, method_name, params = self.parse_label_name(label_name)
        class_name = '' if class_name is None else f' in class {class_name}'
        method_name = '' if method_name is None else f' func {method_name}'
        params = '' if params is None else f'({params})'

        current_procedure_address = self.document.getCurrentAddress()
        pseudo_code = self.procedure.decompile()
        method_signature = f'{method_name}{params}'
        codes = f'{method_signature} {{\n{pseudo_code}\n}}\n\n'

        print(f"Explaining procedure{method_name} at address {current_procedure_address}{class_name}:\n{codes}")
        describe = self.ask_gpt(f"""
Can you describe and breakdown what this procedure does? include parameters? and don't forget to explain the instruction set meaning in the pseudo code
Here is pseudo code:
{codes}
""")
        print(f"Description for method at address {current_procedure_address}: {describe}")
        del codes
        gc.collect()

document = Document.getCurrentDocument()
explainer = CodeExplainer(document)
explainer.explain_procedure()
