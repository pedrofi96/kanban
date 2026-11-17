# Deploy de aplicações Django — resumo de estudo

Resumo do que conversamos sobre colocar uma aplicação Django no ar (OKD), servidores
de aplicação, WSGI/ASGI, WebSocket e Redis. No fim há um checklist, um glossário e um
plano de estudo.

---

## 1. A ideia central: quem faz o quê

O Django **não atende a rede sozinho**. Ele é um conjunto de funções que recebem um
`request` e devolvem uma `response` (as views). Alguém precisa fazer o papel de "porteiro".

```
navegador → Route do OKD (proxy/HTTPS) → servidor de aplicação → Django → banco
```

| Peça | Papel | Exemplos |
|---|---|---|
| Proxy / Route | Endereço público, HTTPS, distribui entre pods | Route do OKD (HAProxy), nginx |
| Servidor de aplicação | Abre a porta, entende HTTP, chama o Django, gerencia processos | gunicorn (WSGI), Daphne / Uvicorn (ASGI) |
| Aplicação | Regras do sistema | Django (suas views, models...) |
| Serviços de apoio | Coisas que rodam separadas | PostgreSQL, Redis |

Comparação: o Django é a **cozinha** (sabe as receitas); o servidor de aplicação é o
**salão com os garçons** (recebe o cliente, leva o pedido, devolve o prato).

---

## 2. WSGI e ASGI: os "contratos"

São padrões que definem **como o servidor chama a aplicação Python**. Por existirem,
dá para trocar o servidor sem mexer no Django.

| | WSGI | ASGI |
|---|---|---|
| Arquivo no projeto | `<projeto>/wsgi.py` | `<projeto>/asgi.py` |
| Modelo | síncrono: um pedido por vez em cada worker | assíncrono: muitas conexões ao mesmo tempo |
| Suporta WebSocket | não | sim |
| Servidores | gunicorn, uWSGI, mod_wsgi | Daphne, Uvicorn (ou gunicorn com worker do Uvicorn) |
| Quando usar | site/API comum | precisa de tempo real (WebSocket), como o kanban |

---

## 3. `runserver` x servidor de produção

O `runserver` também é um servidor de aplicação, mas **só para desenvolvimento**.

| | `runserver` | gunicorn / Daphne |
|---|---|---|
| Feito para | o seu computador | produção |
| Recarrega quando o código muda | sim | não |
| Serve CSS/JS | sim, mas só com `DEBUG=True` | não |
| Vários processos (workers) | não | gunicorn: sim; Daphne: um processo (escala com réplicas) |
| Worker travou/morreu | — | o gerente mata e cria outro |
| Pedido demorando demais | espera para sempre | corta no `timeout` |
| Pensado para carga e segurança | não | sim |

**Como descobrir o que está rodando no OKD:** Workloads → Pods → (pod) → Logs.
As primeiras linhas dizem:

- `---> Serving application with gunicorn` → certo.
- `---> Serving application with 'manage.py runserver'` → servidor de desenvolvimento em
  produção. Foi o caso do sistema de telefonia.

---

## 4. Como o OKD monta a aplicação (S2I de Python)

Ao usar "Import from Git", o OKD usa o **S2I** (Source-to-Image): pega o código do GitLab
e monta a imagem sozinho. Para ver qual estratégia está em uso: Builds → BuildConfigs
(*Source* = S2I; *Docker* = Dockerfile no repositório).

### O que o S2I faz sozinho

- `pip install -r requirements.txt` → **o `requirements.txt` precisa estar completo**.
- `python manage.py collectstatic` no build.
- `python manage.py migrate` ao subir o pod.
- Usa a porta **8080**.
- Escolhe o servidor: se o `gunicorn` está no `requirements.txt`, usa gunicorn; se não,
  **cai no `runserver` sem dar erro** (só um aviso no log).

### Variáveis de ambiente do S2I que vale conhecer

| Variável | Para quê |
|---|---|
| `APP_MODULE` | Qual aplicação o gunicorn carrega. Ex.: `core.wsgi:application` |
| `WEB_CONCURRENCY` | Número de workers do gunicorn. Ex.: `2` |
| `APP_SCRIPT` | Script próprio para iniciar (usado para rodar o Daphne/ASGI) |
| `APP_CONFIG` | Arquivo de configuração do gunicorn |
| `DISABLE_COLLECTSTATIC` | Não rodar o `collectstatic` no build |
| `DISABLE_MIGRATE` | Não rodar o `migrate` ao subir |

> Confirme os nomes na documentação da imagem S2I de Python usada pelo seu OKD
> (projeto `sclorg/s2i-python-container`), pois podem variar entre versões.

---

## 5. Configurações do Django para produção

| Item | Por quê |
|---|---|
| `DEBUG=False` | Com `True`, qualquer erro mostra código e configurações na tela. |
| `SECRET_KEY` em variável de ambiente, guardada num **Secret** do OKD | Secret não aparece em texto aberto no Deployment. Vale também para a senha do banco. |
| `ALLOWED_HOSTS` | Precisa ter o endereço da Route. |
| `CSRF_TRUSTED_ORIGINS` | Com HTTPS, precisa ter `https://<endereço da Route>`. |
| `requirements.txt` completo | Gerado com `pip freeze > requirements.txt` dentro do venv. |
| Arquivos estáticos (CSS/JS) | O servidor de produção não serve. Use o `whitenoise` (abaixo). |
| Arquivos enviados por usuários (media) | Precisam de volume persistente (PVC), senão somem quando o pod reinicia. |
| Health checks (probes) | O OKD reinicia a aplicação sozinho se ela travar. |
| Webhook do GitLab (opcional) | Cada push dispara o build automaticamente. |

### Arquivos estáticos com whitenoise

1. `pip install whitenoise` (e atualizar o `requirements.txt`).
2. Em `MIDDLEWARE`, logo depois de `SecurityMiddleware`:
   `"whitenoise.middleware.WhiteNoiseMiddleware",`
3. Ter `STATIC_ROOT` definido (o S2I roda o `collectstatic` no build).

**Pegadinha:** se hoje o CSS aparece com `runserver`, provavelmente `DEBUG=True`. Ao trocar
para gunicorn com `DEBUG=False`, o CSS some se não houver whitenoise.

### A checagem automática do Django

```bash
python manage.py check --deploy
```

Rodando com as configurações de produção, aponta o que está inseguro.

---

## 6. Tempo real: WebSocket, Channels, Daphne e Redis (o caso do kanban)

### Como funciona no kanban

- O **WebSocket** só avisa "o quadro mudou". Os dados continuam vindo pela API JSON,
  onde ficam as permissões.
- O **Channels** é a biblioteca que traz WebSocket para o Django (consumers, grupos,
  `channel_layer`).
- O **Daphne** é o servidor ASGI que atende HTTP **e** WebSocket.
- O **Redis** é o "correio" entre processos: quando uma view em um pod manda o aviso, o
  Redis entrega para quem está conectado em qualquer outro pod.

### Quem instala o quê

| Peça | Como chega no servidor |
|---|---|
| Daphne, Channels, channels-redis | Pacotes Python → vêm pelo `requirements.txt` no build. Nada a instalar no servidor. |
| Redis | **Serviço separado**: outro deploy no OKD (com um Service). A aplicação não instala. Não precisa de volume persistente. |

A aplicação só precisa saber o endereço:

```
REDIS_URL=redis://redis:6379      # "redis" = nome do Service no OKD
```

Sem `REDIS_URL`, o kanban usa o `InMemoryChannelLayer`, que **só funciona com um único
processo**. Com 2+ pods (ou 2+ workers), os avisos não chegam a todo mundo.

### O que muda no deploy do kanban

1. **Comando de execução (ASGI).** Ex.: um `app.sh` no repositório, apontado por `APP_SCRIPT`:

   ```bash
   #!/bin/bash
   exec daphne -b 0.0.0.0 -p 8080 config.asgi:application
   ```

   - `-b 0.0.0.0`: aceita conexões de fora do container.
   - `-p 8080`: a mesma porta do Service.
   - No Windows, o arquivo precisa ficar marcado como executável no Git:
     `git update-index --chmod=+x app.sh`.
   - Confira no log se o `migrate` ainda roda com `APP_SCRIPT`; se não, coloque
     `python manage.py migrate --noinput` no script antes do `exec`.
   - Alternativa mantendo gunicorn:
     `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080`
2. **Escala:** o Daphne é um processo só. Para mais carga, aumente as **réplicas** (pods) —
   por isso o Redis é necessário.
3. **Route:** aceita WebSocket sem configuração, mas fecha conexões paradas em ~30 s.
   Aumente com a anotação:
   `haproxy.router.openshift.io/timeout: 1h`
   (o front do kanban reconecta sozinho, mas assim evita reconexões à toa).
4. **`ALLOWED_HOSTS`:** o `AllowedHostsOriginValidator` recusa o WebSocket se o endereço
   da Route não estiver lá.

### Testar o Redis no Windows

O Redis não roda nativamente no Windows. Opções: Docker Desktop
(`docker run -p 6379:6379 redis`) ou WSL. Sem Redis, o desenvolvimento local segue com o
InMemory (um processo só, funciona igual).

---

## 7. Cache do navegador e atualizações

- O `?v=N` no `<script src="app.js?v=N">` obriga o navegador a baixar o arquivo novo —
  **mas só quando a página é carregada de novo**.
- Abas que já estavam abertas continuam com o JavaScript antigo até um F5. Foi o que
  aconteceu no teste do tempo real (uma aba não recebia avisos).
- Depois de publicar uma versão nova, avise os usuários para recarregar a página.
- Lembrete: aumentar o `?v=N` sempre que mudar o `app.js`.

---

## 8. Checklists

### Sistema de telefonia (hoje em `runserver`)

- [ ] Adicionar `gunicorn` ao `requirements.txt`.
- [ ] Variável `APP_MODULE=core.wsgi:application` (e, opcionalmente, `WEB_CONCURRENCY=2`).
- [ ] Conferir `DEBUG` no OKD; deixar `False`.
- [ ] Adicionar `whitenoise` e conferir `STATIC_ROOT`.
- [ ] `SECRET_KEY` e senha do banco em Secret.
- [ ] `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` com o endereço da Route.
- [ ] Rodar `python manage.py check --deploy`.
- [ ] Novo build e conferir no log: `Serving application with gunicorn`.

### Kanban (WebSocket)

- [ ] `requirements.txt` atualizado (channels, daphne, channels-redis, psycopg, python-dotenv, whitenoise).
- [ ] Rodar a migração `0003_quadro_concluido` no banco.
- [ ] Redis rodando como deploy separado no OKD + `REDIS_URL`.
- [ ] `app.sh` com o Daphne + `APP_SCRIPT`.
- [ ] Anotação de timeout na Route.
- [ ] Itens de produção da seção 5 (`DEBUG`, Secret, hosts, estáticos).
- [ ] Testar com duas pessoas/navegadores após o deploy.

---

## 9. Glossário rápido

- **Servidor de aplicação:** programa que recebe HTTP e chama o código Python (gunicorn, Daphne).
- **WSGI / ASGI:** padrões de conversa entre servidor e aplicação (síncrono / assíncrono).
- **Worker:** processo que atende pedidos; o gunicorn cria vários.
- **Réplica / pod:** uma cópia da aplicação rodando no OKD.
- **Service (OKD):** nome fixo de rede para alcançar pods (ex.: `redis`).
- **Route (OKD):** endereço público que leva até o Service.
- **Secret (OKD):** variável sensível guardada de forma protegida.
- **S2I:** monta a imagem a partir do código no Git.
- **PVC:** volume de disco que sobrevive ao reinício do pod.
- **Probe:** verificação periódica de que a aplicação está viva.
- **Channel layer:** como o Channels troca mensagens entre processos (InMemory ou Redis).
- **Proxy reverso:** fica na frente da aplicação e repassa os pedidos (a Route faz isso).

---

## 10. O que estudar (em ordem)

1. **Documentação do Django — "How to deploy Django"**: WSGI, ASGI e servidores.
2. **Documentação do Django — "Deployment checklist"** + `manage.py check --deploy`.
3. **Documentação do gunicorn** — seções "Design" (modelo de workers) e "Settings".
4. **Documentação do Channels** — "Deploying" e "Channel Layers".
5. **Documentação da imagem S2I de Python** (`sclorg/s2i-python-container`) — variáveis de ambiente.
6. **Conceitos de OpenShift/Kubernetes**: Pod, Deployment, Service, Route, Secret, PVC,
   probes (documentação do OKD/OpenShift, seção "Building applications").
7. **whitenoise** — página "Using WhiteNoise with Django".
8. **HTTP básico** (MDN — "An overview of HTTP"): ajuda a entender proxies, cabeçalhos e cache.

### Exercícios para fixar

1. Num projeto Django de teste, rode com `runserver` e depois com `gunicorn` (ou Daphne
   no Windows) e compare: o CSS carrega? O que muda com `DEBUG=False`?
2. Adicione o whitenoise e veja o CSS voltar.
3. Rode `check --deploy` e corrija cada aviso, entendendo o motivo de cada um.
4. Corrija o sistema de telefonia seguindo o checklist e acompanhe o log do build e do pod.
5. Suba um Redis no Docker local, coloque `REDIS_URL` no `.env` do kanban e teste o tempo
   real em dois navegadores.

### Perguntas para fazer em todo deploy

- O que roda a aplicação (qual servidor)? Está no log?
- Quem serve os arquivos estáticos?
- Onde estão as senhas e chaves? Estão protegidas?
- O que acontece se o pod reiniciar? (dados, uploads, conexões)
- O que acontece com 2 réplicas? (sessão, cache, WebSocket)
- Como eu sei que a aplicação está viva? (probes, logs)
