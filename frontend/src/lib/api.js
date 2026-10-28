import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
export { BACKEND_URL };

const http = axios.create({ baseURL: API });

export const listServers = () => http.get("/servers").then((r) => r.data);
export const createServer = (payload) => http.post("/servers", payload).then((r) => r.data);
export const updateServer = (id, payload) => http.put(`/servers/${id}`, payload).then((r) => r.data);
export const deleteServer = (id) => http.delete(`/servers/${id}`).then((r) => r.data);
export const connectServer = (id) => http.post(`/servers/${id}/connect`).then((r) => r.data);
export const disconnectServer = (id) => http.post(`/servers/${id}/disconnect`).then((r) => r.data);
export const browseServer = (id, nodeId) =>
    http.get(`/servers/${id}/browse`, { params: nodeId ? { node_id: nodeId } : {} }).then((r) => r.data);

export const listTags = (serverId) =>
    http.get("/tags", { params: serverId ? { server_id: serverId } : {} }).then((r) => r.data);
export const createTag = (payload) => http.post("/tags", payload).then((r) => r.data);
export const updateTag = (id, payload) => http.put(`/tags/${id}`, payload).then((r) => r.data);
export const deleteTag = (id) => http.delete(`/tags/${id}`).then((r) => r.data);

export const getRuntime = () => http.get("/runtime").then((r) => r.data);
export const startRuntime = (format, serial_port, baudrate) =>
    http.post("/runtime/start", { format, serial_port: serial_port || null, baudrate }).then((r) => r.data);
export const stopRuntime = () => http.post("/runtime/stop").then((r) => r.data);
export const setFormat = (format) => http.post("/runtime/format", { format }).then((r) => r.data);

export const getSink = () => http.get("/sink").then((r) => r.data);
export const listSinkTags = () => http.get("/sink/tags").then((r) => r.data);
export const startSink = (serial_port, baudrate, silence_timeout) =>
    http.post("/sink/start", { serial_port, baudrate, silence_timeout }).then((r) => r.data);
export const configSink = (silence_timeout) => http.post("/sink/config", { silence_timeout }).then((r) => r.data);
export const estimateLink = (format, baudrate) => http.get("/runtime/estimate", { params: { format, baudrate } }).then((r) => r.data);
export const getSerialPorts = () => http.get("/serial/ports").then((r) => r.data);
export const stopSink = () => http.post("/sink/stop").then((r) => r.data);
