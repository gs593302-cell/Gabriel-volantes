# Gabriel Volantes — assistente de WhatsApp

Protótipo para revestimento em couro costurado: identifica carro e ano, confirma
o volante por foto do catálogo, apresenta R$269 no Pix ou em até quatro vezes
sem juros (deslocamento incluso) e pausa ao encaminhar o cliente para Gabriel.
Gabriel combina e confirma a agenda: sexta-feira após as 12h ou sábado.

**Estado atual:** testes locais passam, com APIs externas simuladas. Não há
implantação pública nem conexão real com a OpenAI ou o WhatsApp. O catálogo
começa vazio: nesse caso o assistente solicita foto e encaminha para Gabriel,
sem inventar um exemplo compatível. Não usar com clientes antes da validação
com o número de teste e da preparação do atendimento manual.

## Execução e configuração

Python 3.12, somente biblioteca padrão, sem dependências para instalar.
Use o checkout existente em `/workspace/Gabriel-volantes`; cada tarefa na nuvem
já é isolada e não precisa de worktree adicional.

```sh
cd /workspace/Gabriel-volantes
python3 -m unittest -v
python3 app.py
```

O segundo comando exige as variáveis abaixo. Cadastre valores somente no painel
de segredos da hospedagem (ou no ambiente do processo local), nunca no Git ou no
chat. O aplicativo não carrega arquivos `.env` automaticamente.

| Variável | Uso |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | Token da Meta com acesso ao número de teste. Revogue o token exposto no chat e não o reutilize. |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone Number ID do número de teste, não o número de telefone nem o ID da conta. |
| `META_APP_SECRET` | Segredo do aplicativo Meta, para validar assinaturas. |
| `WEBHOOK_VERIFY_TOKEN` | Segredo aleatório criado por você, idêntico ao campo “Verificar token” na Meta. Não é o token de acesso. |
| `OPENAI_API_KEY` | Chave de um projeto da API OpenAI, com faturamento e limite definidos. A assinatura do ChatGPT não inclui créditos da API. |
| `ADMIN_TOKEN` | Outro segredo aleatório para abrir o painel de repasses; diferente dos demais. |
| `DATABASE_PATH` | Arquivo SQLite em disco persistente; padrão local `data/assistant.sqlite3`. |
| `PORT` | Porta interna fornecida pela hospedagem; padrão 8000. |
| `OPENAI_MODEL` | Opcional, padrão `gpt-4.1-mini`; precisa estar disponível no projeto OpenAI. |

Para os dois segredos novos, use um gerenciador de senhas e gere valores
independentes com pelo menos 32 caracteres aleatórios. Não envie esses valores
em prints. Credenciais ausentes impedem a inicialização.

Destinos HTTPS necessários: `graph.facebook.com` e `api.openai.com`, além dos
hosts das imagens reais. Preserve a verificação TLS e o proxy/CA da plataforma.

## Catálogo

Edite `catalog.json` com fotos reais aprovadas. Exemplo de estrutura (a URL é
ilustrativa, substitua antes de usar):

```json
[
  {
    "model": "Corolla",
    "year_from": 2016,
    "year_to": 2016,
    "image_url": "https://seu-dominio.com/fotos/corolla-2016.jpg"
  }
]
```

Não deduza faixas de ano apenas pela aparência. Se houver duas variantes
cadastradas para o mesmo carro/ano, o sistema pede uma foto para análise humana.
As imagens devem estar acessíveis à Meta por HTTPS sem credenciais na URL.

## Hospedagem sugerida: serviço web Python com disco persistente

Um serviço como Render pode executar este protótipo; a conta e eventuais custos
precisam ser definidos pelo proprietário. Este repositório ainda precisa ser
publicado no GitHub para a implantação por integração Git.

1. Crie um Web Service ligado ao repositório, escolhendo Python 3.
2. Use Python 3.12.14 (na Render, a variável `PYTHON_VERSION` seleciona a versão).
3. Diretório raiz: o diretório que contém `app.py`; na raiz deste repo, deixe vazio.
4. Build: `python3 -m compileall -q app.py assistant_flow.py`.
5. Start: `python3 app.py`.
6. Cadastre as credenciais no painel de variáveis/segredos.
7. Monte um disco persistente, por exemplo `/var/data`, e defina
   `DATABASE_PATH=/var/data/gabriel.sqlite3`.
8. Execute **uma instância e um processo**. O SQLite e a fila deste protótipo não
   foram projetados para múltiplos workers ou réplicas.
9. Configure health check `/health`. Depois de iniciar, faça um GET nesse caminho
   na URL HTTPS pública e verifique `{"status":"ok"}`.

Escolha um serviço que permaneça ativo para atender 24h; um plano que suspenda
o processo pode atrasar ou perder atendimento. O disco precisa sobreviver a
reinícios/deploys; não use apenas o sistema de arquivos temporário do serviço.

## Conectar na Meta, após a hospedagem

1. URL de callback: `https://SEU-SERVICO/webhook`, usando o endereço real.
2. “Verificar token”: o mesmo valor seguro de `WEBHOOK_VERIFY_TOKEN`.
3. Clique em verificar e salvar; assine o campo `messages` para a conta WhatsApp.
4. Siga os requisitos exibidos no painel quanto a publicação e permissões. A tela
   atual avisa que apps não publicados recebem somente testes enviados pelo painel;
   não presuma que mensagens de clientes reais serão entregues nessa condição.
5. Primeiro valide um webhook de teste do painel. Depois valide recebimento e
   resposta com o número de teste e destinatário autorizado, quando permitido.

Se a verificação falhar, confira o token, a URL e o log de inicialização; nunca
desative a validação de assinatura. A assinatura usa `META_APP_SECRET` e o header
`X-Hub-Signature-256`. A verificação GET usa outro segredo: `WEBHOOK_VERIFY_TOKEN`.

## Roteiro de teste real antes de produção

- Cadastrar uma foto válida, informar carro/ano e confirmar o volante.
- Verificar envio da foto, orçamento correto e coleta de cidade/bairro/preferência.
- Aceitar o orçamento e confirmar que a conversa fica pausada, sem reservar horário.
- Consultar `https://SEU-SERVICO/panel`, entrar com `ADMIN_TOKEN` e conferir o resumo.
- Mandar nova mensagem após o repasse e confirmar que não há resposta automática.
- Testar pedido de atendimento humano, pedido de parar, volante sem catálogo e áudio.
- Reiniciar o serviço e conferir que histórico, pausa e fila permanecem no disco.

Nenhum desses testes de API externa foi executado neste ambiente. Os testes
automatizados fazem requisições HTTP locais e simulam a OpenAI e o envio da Meta.

## Repasse e limites do protótipo

O painel `/panel` é apenas de consulta: atualize-o para ver novos repasses. Não há
notificação automática para Gabriel nem envio manual pelo painel. `/handoffs`
retorna os mesmos dados em JSON, exigindo `Authorization: Bearer ADMIN_TOKEN`.
O painel não inclui mídia; imagens e áudios recebidos são encaminhados para
análise humana, sem reconhecimento visual ou transcrição automática nesta versão.

Antes de produção, escolher e validar o canal no qual Gabriel vai efetivamente
responder: coexistência oficial com o aplicativo WhatsApp Business, se elegível,
ou uma caixa de entrada com envio pela API. Não migrar nem desativar o número
atual antes dessa validação. Um número de teste da API não equivale a uma conta
que você possa abrir no aplicativo para assumir as conversas.

Erros de API ou entrega incerta pausam o contato para revisão, sem reenvio cego.
Mensagens duplicadas usam o ID da Meta para deduplicação. Conversas fora da
janela segura de 23h são pausadas; não há envio de templates ou campanhas.
Não há retomada automática de contatos pausados. Para uso contínuo, faltam
controles de retomada, canal de resposta humana, política de retenção/remoção
dos dados, backup do disco e alertas de falha. Históricos, telefones e mensagens
ficam no SQLite; proteja e limite acesso ao disco e ao painel.

O preço e as condições saem de textos fixos. A IA extrai dados e intenção; ela
não escolhe descontos, imagens por adivinhação nem horários. Essa extração ainda
precisa de validação real com diferentes mensagens antes de atender clientes.
