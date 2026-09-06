package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;



import java.io.IOException;
import java.util.Map;

public abstract class DataSet {
    public abstract void auth(String token);

    public abstract void auth(String username, String password);
    public abstract void download(String output, String datatype, Metadata metadata) throws IOException;
    public abstract boolean authorized();
    public abstract String[] getDatatypes();
}