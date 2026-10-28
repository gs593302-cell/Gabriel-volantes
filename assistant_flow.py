"""Business rules. The model extracts facts; prices and handoff remain in code."""
import json
import unicodedata


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower())
                   if not unicodedata.combining(c)).strip()


def advance(state, facts, catalog):
    state = dict(state)
    if state.get('paused'):
        return state, []
    for key in ('model', 'year', 'city', 'neighborhood', 'preferred_day'):
        if facts.get(key):
            state[key] = facts[key]
    intent = facts.get('intent', 'other')
    if intent == 'stop':
        state.update(paused=True, reason='Cliente pediu para parar')
        return state, [{'text': 'Tudo bem. Vou pausar as mensagens por aqui.'}]
    if intent == 'human':
        state.update(paused=True, reason='Cliente pediu atendimento humano')
        return state, [{'text': 'Vou passar seu atendimento para o Gabriel. Ele continuará a conversa com você.'}]
    if not state.get('introduced'):
        state['introduced'] = True
        intro = 'Olá, tudo certo? 👊 Sou o assistente virtual da Gabriel Volantes. '
    else:
        intro = ''
    if not state.get('model') or not state.get('year'):
        missing = ('o modelo e o ano' if not state.get('model') and not state.get('year')
                   else 'o modelo' if not state.get('model') else 'o ano')
        return state, [{'text': intro + f'Qual é {missing} do seu carro? Trabalhamos com revestimento em couro costurado para volantes.'}]
    identity = f"{normalized(state['model'])}:{state['year']}"
    if state.get('vehicle_key') != identity:
        for key in ('wheel_confirmed', 'offered', 'awaiting_confirmation', 'photo_requested', 'accepted'):
            state.pop(key, None)
        state['vehicle_key'] = identity
    matches = [c for c in catalog if normalized(c['model']) == normalized(state['model'])
               and c['year_from'] <= state['year'] <= c['year_to']]
    # Never guess a photo when variants or years are ambiguous.
    if not state.get('wheel_confirmed'):
        if len(matches) != 1:
            if facts.get('has_image'):
                state.update(paused=True, reason='Foto recebida: identificar volante manualmente')
                return state, [{'text': intro + 'Recebi sua foto! O Gabriel vai conferir o modelo do volante e continuar seu orçamento.'}]
            state['photo_requested'] = True
            return state, [{'text': intro + 'Pode enviar uma foto do volante atual? Preciso confirmar o modelo para continuar seu orçamento.'}]
        if state.get('awaiting_confirmation') and not state.get('photo_requested') and intent == 'confirm':
            state['wheel_confirmed'] = True
        elif state.get('awaiting_confirmation') and intent == 'reject':
            state['photo_requested'] = True
            if facts.get('has_image'):
                state.update(paused=True, reason='Volante diferente do catálogo: foto recebida')
                return state, [{'text': 'O Gabriel vai conferir sua foto e continuar o atendimento.'}]
            return state, [{'text': 'Pode enviar uma foto do seu volante para o Gabriel conferir?'}]
        elif facts.get('has_image'):
            state.update(paused=True, reason='Foto recebida: conferir volante')
            return state, [{'text': 'O Gabriel vai conferir sua foto e continuar o atendimento.'}]
        elif state.get('photo_requested'):
            return state, [{'text': 'Envie uma foto do seu volante para o Gabriel conferir o modelo.'}]
        else:
            state['awaiting_confirmation'] = True
            return state, [{'image': matches[0]['image_url'],
                            'caption': intro + 'Este é um trabalho nosso. O volante do seu carro é igual a este?'}]
    if not state.get('offered'):
        state['offered'] = True
        return state, [{'text': 'O revestimento em couro costurado custa R$269 no Pix ou em até 4 vezes sem juros, com deslocamento incluso. 👊\n\nInclui acabamento feito à mão, higienização completa e 1 ano de garantia. O serviço leva aproximadamente 1 hora, sem retirar o volante.\n\nQuer seguir para combinar o atendimento?'}]
    if intent == 'accept':
        state['accepted'] = True
    if state.get('accepted'):
        missing = []
        if not state.get('city'):
            missing.append('cidade')
        if not state.get('neighborhood'):
            missing.append('bairro')
        if missing:
            return state, [{'text': 'Perfeito! Qual é ' + ('sua cidade e seu bairro' if len(missing) == 2 else 'sua cidade' if missing[0] == 'cidade' else 'seu bairro') + '?'}]
        if not state.get('preferred_day'):
            return state, [{'text': 'Você prefere sexta-feira após as 12h ou sábado? O Gabriel vai confirmar o horário disponível.'}]
        state.update(paused=True, reason='Orçamento aceito: combinar agenda')
        return state, [{'text': 'Perfeito! 👊 Vou passar seu atendimento para o Gabriel, que vai combinar com você o horário disponível. Seu agendamento será confirmado por ele.'}]
    if intent == 'reject':
        return state, [{'text': 'Tudo bem! Se quiser retomar o orçamento, é só chamar.'}]
    if intent == 'availability':
        return state, [{'text': 'Atendemos sexta-feira após as 12h ou sábado. O Gabriel consulta a agenda e confirma o horário com você. Quer seguir com o orçamento de R$269?'}]
    if intent == 'price':
        return state, [{'text': 'São R$269 no Pix ou em até 4 vezes sem juros, com deslocamento incluso. Quer seguir para combinar o atendimento?'}]
    state.update(paused=True, reason='Dúvida fora das respostas cadastradas')
    return state, [{'text': 'Vou passar sua dúvida para o Gabriel, para ele te orientar certinho.'}]


def load_catalog(path):
    with open(path, encoding='utf-8') as file:
        catalog = json.load(file)
    for item in catalog:
        if (not item.get('model') or not isinstance(item.get('year_from'), int)
                or not isinstance(item.get('year_to'), int)
                or item['year_from'] > item['year_to']
                or not item.get('image_url', '').startswith('https://')):
            raise ValueError('Entrada inválida no catálogo')
    return catalog
