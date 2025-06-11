from dotenv import load_dotenv
from utils.src.utils import get_json_from_response

from camel.models import ModelFactory
from camel.agents import ChatAgent


from utils.wei_utils import account_token, get_agent_config, html_to_png

from utils.pptx_utils import *
from utils.critic_utils import *
import yaml
import time
from jinja2 import Environment, StrictUndefined
from utils.poster_eval_utils import get_poster_text
import argparse
import json
import os

load_dotenv()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--paper_path', type=str)
    parser.add_argument('--model_name', type=str, default='gemini-2.5-pro')

    args = parser.parse_args()

    # get current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    meta_dir = args.paper_path.replace('paper.pdf', 'meta.json')
    meta = json.load(open(meta_dir, 'r'))
    poster_width = meta['width']
    poster_height = meta['height']

    output_dir = f"{args.model_name}_HTML/{args.paper_path.replace('paper.pdf', '')}"
    os.makedirs(output_dir, exist_ok=True)

    total_input_token = 0
    total_output_token = 0

    start_time = time.time()
    model_config = get_agent_config(args.model_name)
    model = ModelFactory.create(
        model_platform=model_config['model_platform'],
        model_type=model_config['model_type'],
        model_config_dict=model_config['model_config'],
    )
    paper_text = get_poster_text(args.paper_path)

    actor_agent_name = 'LLM_gen_HTML'

    with open(f'prompt_templates/{actor_agent_name}.yaml', "r") as f:
        content_config = yaml.safe_load(f)
    jinja_env = Environment(undefined=StrictUndefined)
    template = jinja_env.from_string(content_config["template"])

    actor_sys_msg = content_config['system_prompt']
    actor_agent = ChatAgent(
        system_message=actor_sys_msg,
        model=model,
        message_window_size=None
    )

    jinja_args = {
        'document_markdown': paper_text,
        'poster_width': poster_width,
        'poster_height': poster_height,
    }
    prompt = template.render(**jinja_args)

    actor_agent.reset()
    response = actor_agent.step(prompt)
    input_token, output_token = account_token(response)
    total_input_token += input_token
    total_output_token += output_token
    result_json = get_json_from_response(response.msgs[0].content)
    html_str = result_json['HTML']

    # write to poster.html
    with open(f'{output_dir}/poster.html', 'w') as f:
        f.write(html_str)

    html_to_png(
        os.path.join(current_dir, output_dir, 'poster.html'), 
        poster_width, 
        poster_height, 
        os.path.join(current_dir, output_dir, 'poster.png')
    )


    end_time = time.time()
    elapsed_time = end_time - start_time

    log = {
        'input_token': total_input_token,
        'output_token': total_output_token,
        'time_taken': elapsed_time
    }

    with open(f'{output_dir}/log.json', 'w') as f:
        json.dump(log, f, indent=4)
