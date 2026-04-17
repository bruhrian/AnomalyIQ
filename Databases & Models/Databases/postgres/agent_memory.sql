--
-- PostgreSQL database dump
--

\restrict cCRQDWHyVy6wSsSM2vV132Qjbnf5ha8NlenTv09es5u5g8hZndjShX7I0ydZ3uh

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: message_store; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.message_store (
    id integer NOT NULL,
    session_id character varying(255) NOT NULL,
    message text NOT NULL
);


ALTER TABLE public.message_store OWNER TO postgres;

--
-- Name: message_store_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.message_store_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.message_store_id_seq OWNER TO postgres;

--
-- Name: message_store_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.message_store_id_seq OWNED BY public.message_store.id;


--
-- Name: message_types; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.message_types (
    id integer NOT NULL,
    name character varying(50) NOT NULL
);


ALTER TABLE public.message_types OWNER TO postgres;

--
-- Name: message_types_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.message_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.message_types_id_seq OWNER TO postgres;

--
-- Name: message_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.message_types_id_seq OWNED BY public.message_types.id;


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sessions (
    id integer NOT NULL,
    session_id character varying(255) NOT NULL,
    agent_name character varying(100) DEFAULT 'orchestrator'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_active_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.sessions OWNER TO postgres;

--
-- Name: sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sessions_id_seq OWNER TO postgres;

--
-- Name: sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sessions_id_seq OWNED BY public.sessions.id;


--
-- Name: message_store id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_store ALTER COLUMN id SET DEFAULT nextval('public.message_store_id_seq'::regclass);


--
-- Name: message_types id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_types ALTER COLUMN id SET DEFAULT nextval('public.message_types_id_seq'::regclass);


--
-- Name: sessions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sessions ALTER COLUMN id SET DEFAULT nextval('public.sessions_id_seq'::regclass);


--
-- Data for Name: message_store; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.message_store (id, session_id, message) FROM stdin;
1	orchestrator-default-session	{"type": "human", "data": {"content": "hello", "additional_kwargs": {}, "response_metadata": {}, "type": "human", "name": null, "id": null}}
2	orchestrator-default-session	{"type": "ai", "data": {"content": "Hello! I am Ryan, an orchestrator AI agent. I'm here to help you break down complex goals into manageable steps and get them done.\\n\\nWhat can I help you with today? Please tell me what you would like to accomplish!", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": null, "id": null, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": null}}
3	orchestrator-default-session	{"type": "human", "data": {"content": "help me insert new data into one of the tables.", "additional_kwargs": {}, "response_metadata": {}, "type": "human", "name": null, "id": null}}
4	orchestrator-default-session	{"type": "ai", "data": {"content": "I can certainly help you with that, but I need a few more details first. Database operations require precision!\\n\\nTo ensure I modify the correct data and structure, could you tell me the following:\\n\\n1.  **Which database table** are you trying to insert data into?\\n2.  **What specific data** do you want to insert? (e.g., \\"A new user named John Doe with the email john@example.com\\").\\n3.  Do you know the **column names** and the **data types** for the information you are providing?\\n\\nOnce I have this information, I will use the database agent to perform the insertion safely.", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": null, "id": null, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": null}}
5	orchestrator-default-session	{"type": "human", "data": {"content": "what are the available tables I have in my database?", "additional_kwargs": {}, "response_metadata": {}, "type": "human", "name": null, "id": null}}
6	orchestrator-default-session	{"type": "ai", "data": {"content": "Thank you for confirming the available tables. I see we have the following tables: `alert_actions`, `alerts`, `cameras`, `cctv`, `event`, `event_types`, `locations`, and `users`.\\n\\nPlease tell me:\\n\\n1.  **Which specific table** do you want to insert data into? (e.g., `users`, `locations`, `cameras`, etc.)\\n2.  **What column(s)** should the data go into? (Refer to the columns listed above.)\\n3.  **What is the exact data** for those columns?\\n\\n***\\n\\n**Example:** *If you wanted to add a new location,* you would tell me: \\"Use the `locations` table. Insert the `location_name` as 'Warehouse B' and the `address` as '123 industrial way'.\\"\\n\\nI am ready when you are!", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": null, "id": null, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": null}}
7	orchestrator-default-session	{"type": "human", "data": {"content": "sure, let's add a new location in the locations table. location name is SP, address is 500 dover road.", "additional_kwargs": {}, "response_metadata": {}, "type": "human", "name": null, "id": null}}
8	orchestrator-default-session	{"type": "ai", "data": {"content": "I have successfully added the new location 'SP' at '500 Dover Road' to the `locations` table.\\n\\nIs there anything else I can help you with regarding the database, or is there another task I can assist you with?", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": null, "id": null, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": null}}
\.


--
-- Data for Name: message_types; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.message_types (id, name) FROM stdin;
1	human
2	ai
3	system
4	tool
\.


--
-- Data for Name: sessions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.sessions (id, session_id, agent_name, created_at, last_active_at) FROM stdin;
\.


--
-- Name: message_store_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.message_store_id_seq', 8, true);


--
-- Name: message_types_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.message_types_id_seq', 4, true);


--
-- Name: sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.sessions_id_seq', 1, false);


--
-- Name: message_store message_store_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_store
    ADD CONSTRAINT message_store_pkey PRIMARY KEY (id);


--
-- Name: message_types message_types_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_types
    ADD CONSTRAINT message_types_name_key UNIQUE (name);


--
-- Name: message_types message_types_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_types
    ADD CONSTRAINT message_types_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_session_id_key UNIQUE (session_id);


--
-- Name: idx_message_store_session_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_message_store_session_id ON public.message_store USING btree (session_id);


--
-- Name: idx_sessions_last_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sessions_last_active ON public.sessions USING btree (last_active_at);


--
-- PostgreSQL database dump complete
--

\unrestrict cCRQDWHyVy6wSsSM2vV132Qjbnf5ha8NlenTv09es5u5g8hZndjShX7I0ydZ3uh

